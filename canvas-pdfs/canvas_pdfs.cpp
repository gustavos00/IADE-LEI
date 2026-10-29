// Descarrega os PDFs das tuas cadeiras no Canvas, pela API oficial.
//
// Compilar (macOS já traz a libcurl):
//   clang++ -std=c++17 -O2 canvas_pdfs.cpp -lcurl -o canvas_pdfs
// (Linux: g++ -std=c++17 -O2 canvas_pdfs.cpp -lcurl -o canvas_pdfs, com libcurl-dev instalada)
//
// Antes de correr:
//   1. No Canvas: Conta > Definições > "+ Novo token de acesso". Copia o token.
//   2. export CANVAS_TOKEN="<o token>"
//   3. ./canvas_pdfs
//
// Opções:
//   --saida PASTA     onde guardar (por omissão: ./Faculdade)
//   --todas           inclui cadeiras de semestres anteriores, não só as ativas
//   --listar          mostra o que descarregaria, sem descarregar
//
// Só descarrega as disciplinas em SUBJECTS, para <saida>/<disciplina>/<módulo>/<ficheiro>.pdf.
// Os módulos ficam "01 - Vetores e Matrizes", com os PDFs do módulo em Originais/; os
// "N. Recursos da Aula Virtual" vão para dentro do módulo N. PDFs da área Ficheiros que não estão em nenhum módulo vão para <disciplina>/Outros ficheiros.
// Ficheiros já descarregados (mesmo tamanho) são saltados, por isso podes voltar a correr.

#include <curl/curl.h>

#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

namespace fs = std::filesystem;

// O CANVAS_URL só é preciso para apontar a outro Canvas.
const char* const DEFAULT_CANVAS_URL = "https://www.mycampus.pt";

// ---------- JSON mínimo (só leitura) ----------

struct Json {
    enum class Type { Null, Bool, Number, String, Array, Object };

    Type type = Type::Null;
    bool boolean = false;
    // Os números ficam em texto: os IDs do Canvas podem passar de 2^53 e perder-se num double.
    std::string text;
    std::vector<Json> items;
    std::vector<std::pair<std::string, Json>> members;

    const Json* find(const std::string& key) const {
        for (const auto& [name, value] : members) {
            if (name == key) {
                return &value;
            }
        }

        return nullptr;
    }

    std::string getString(const std::string& key) const {
        const Json* value = find(key);

        return value && (value->type == Type::String || value->type == Type::Number) ? value->text : "";
    }

    bool getBool(const std::string& key) const {
        const Json* value = find(key);

        return value && value->type == Type::Bool && value->boolean;
    }
};

class JsonParser {
public:
    explicit JsonParser(const std::string& source) : source_(source) {}

    Json parseDocument() {
        Json value = parseValue();
        skipSpaces();

        if (position_ != source_.size()) {
            fail("texto a mais");
        }

        return value;
    }

private:
    const std::string& source_;
    size_t position_ = 0;

    [[noreturn]] void fail(const std::string& reason) const {
        throw std::runtime_error("JSON inválido (" + reason + ") na posição " + std::to_string(position_));
    }

    void skipSpaces() {
        while (position_ < source_.size() && std::isspace(static_cast<unsigned char>(source_[position_]))) {
            ++position_;
        }
    }

    char peek() {
        skipSpaces();

        if (position_ >= source_.size()) {
            fail("fim inesperado");
        }

        return source_[position_];
    }

    void expect(char expected) {
        if (peek() != expected) {
            fail(std::string("esperava '") + expected + "'");
        }

        ++position_;
    }

    bool consumeLiteral(const char* literal) {
        size_t length = std::char_traits<char>::length(literal);

        if (source_.compare(position_, length, literal) == 0) {
            position_ += length;

            return true;
        }

        return false;
    }

    Json parseValue() {
        char current = peek();
        Json value;

        if (current == '{') {
            value.type = Json::Type::Object;
            ++position_;

            if (peek() == '}') {
                ++position_;

                return value;
            }

            while (true) {
                std::string key = parseString();
                expect(':');
                value.members.emplace_back(std::move(key), parseValue());

                if (peek() == ',') {
                    ++position_;
                    continue;
                }

                expect('}');

                return value;
            }
        }

        if (current == '[') {
            value.type = Json::Type::Array;
            ++position_;

            if (peek() == ']') {
                ++position_;

                return value;
            }

            while (true) {
                value.items.push_back(parseValue());

                if (peek() == ',') {
                    ++position_;
                    continue;
                }

                expect(']');

                return value;
            }
        }

        if (current == '"') {
            value.type = Json::Type::String;
            value.text = parseString();

            return value;
        }

        if (consumeLiteral("true")) {
            value.type = Json::Type::Bool;
            value.boolean = true;

            return value;
        }

        if (consumeLiteral("false")) {
            value.type = Json::Type::Bool;

            return value;
        }

        if (consumeLiteral("null")) {
            return value;
        }

        size_t start = position_;

        while (position_ < source_.size() && std::strchr("+-0123456789.eE", source_[position_]) != nullptr) {
            ++position_;
        }

        if (start == position_) {
            fail("valor desconhecido");
        }

        value.type = Json::Type::Number;
        value.text = source_.substr(start, position_ - start);

        return value;
    }

    unsigned readHex4() {
        if (position_ + 4 > source_.size()) {
            fail("escape \\u incompleto");
        }

        unsigned code = std::stoul(source_.substr(position_, 4), nullptr, 16);
        position_ += 4;

        return code;
    }

    static void appendUtf8(std::string& output, unsigned code) {
        if (code < 0x80) {
            output += static_cast<char>(code);
        } else if (code < 0x800) {
            output += static_cast<char>(0xC0 | (code >> 6));
            output += static_cast<char>(0x80 | (code & 0x3F));
        } else if (code < 0x10000) {
            output += static_cast<char>(0xE0 | (code >> 12));
            output += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
            output += static_cast<char>(0x80 | (code & 0x3F));
        } else {
            output += static_cast<char>(0xF0 | (code >> 18));
            output += static_cast<char>(0x80 | ((code >> 12) & 0x3F));
            output += static_cast<char>(0x80 | ((code >> 6) & 0x3F));
            output += static_cast<char>(0x80 | (code & 0x3F));
        }
    }

    std::string parseString() {
        expect('"');
        std::string output;

        while (true) {
            if (position_ >= source_.size()) {
                fail("texto por fechar");
            }

            char current = source_[position_++];

            if (current == '"') {
                return output;
            }

            if (current != '\\') {
                output += current;
                continue;
            }

            char escape = source_[position_++];

            switch (escape) {
                case 'n': output += '\n'; break;
                case 't': output += '\t'; break;
                case 'r': output += '\r'; break;
                case 'b': output += '\b'; break;
                case 'f': output += '\f'; break;
                case 'u': {
                    unsigned code = readHex4();

                    if (code >= 0xD800 && code <= 0xDBFF && source_.compare(position_, 2, "\\u") == 0) {
                        position_ += 2;
                        unsigned low = readHex4();
                        code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
                    }

                    appendUtf8(output, code);
                    break;
                }
                default: output += escape;
            }
        }
    }
};

// ---------- HTTP (libcurl) ----------

class HttpError : public std::runtime_error {
public:
    HttpError(long status, const std::string& url)
        : std::runtime_error("HTTP " + std::to_string(status) + " em " + url), status(status) {}

    long status;
};

struct Response {
    std::string body;
    std::string nextUrl;
};

size_t appendToString(char* data, size_t size, size_t count, void* target) {
    static_cast<std::string*>(target)->append(data, size * count);

    return size * count;
}

size_t writeToFile(char* data, size_t size, size_t count, void* target) {
    auto* output = static_cast<std::ofstream*>(target);
    output->write(data, static_cast<std::streamsize>(size * count));

    return *output ? size * count : 0;
}

size_t collectLinkHeader(char* data, size_t size, size_t count, void* target) {
    std::string line(data, size * count);
    std::string lower = line;
    std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return std::tolower(c); });

    if (lower.rfind("link:", 0) == 0) {
        *static_cast<std::string*>(target) = line.substr(5);
    }

    return size * count;
}

std::string parseNextLink(const std::string& header) {
    static const std::regex nextPattern(R"(<([^>]+)>;\s*rel="next")");
    std::smatch match;

    return std::regex_search(header, match, nextPattern) ? match[1].str() : "";
}

class CanvasClient {
public:
    CanvasClient(std::string baseUrl, const std::string& token) : baseUrl_(std::move(baseUrl)) {
        // A libcurl não reenvia um cabeçalho Authorization quando um redirecionamento muda de
        // anfitrião: os downloads acabam num armazenamento externo com o URL já assinado.
        headers_ = curl_slist_append(nullptr, ("Authorization: Bearer " + token).c_str());
    }

    ~CanvasClient() { curl_slist_free_all(headers_); }

    CanvasClient(const CanvasClient&) = delete;
    CanvasClient& operator=(const CanvasClient&) = delete;

    std::vector<Json> fetchAllPages(const std::string& path, const std::string& query = "") {
        std::string url = baseUrl_ + "/api/v1" + path + "?per_page=100" + (query.empty() ? "" : "&" + query);
        std::vector<Json> results;

        while (!url.empty()) {
            Response response = get(url);
            Json page = JsonParser(response.body).parseDocument();

            for (auto& item : page.items) {
                results.push_back(std::move(item));
            }

            url = response.nextUrl;
        }

        return results;
    }

    Json fetchJson(const std::string& path) {
        return JsonParser(get(baseUrl_ + "/api/v1" + path).body).parseDocument();
    }

    void downloadTo(const std::string& url, const fs::path& destination) {
        fs::path partial = destination;
        partial += ".part";
        long status = 0;

        {
            std::ofstream output(partial, std::ios::binary);

            if (!output) {
                throw std::runtime_error("não consegui criar " + partial.string());
            }

            CURLcode result = perform(url, writeToFile, &output, nullptr, 300L, status);

            if (result != CURLE_OK) {
                throw std::runtime_error(curl_easy_strerror(result));
            }
        }

        if (status >= 400) {
            fs::remove(partial);
            throw HttpError(status, url);
        }

        fs::rename(partial, destination);
    }

private:
    std::string baseUrl_;
    curl_slist* headers_ = nullptr;

    CURLcode perform(const std::string& url, curl_write_callback writer, void* writeTarget,
                     std::string* linkHeader, long timeoutSeconds, long& status) {
        std::unique_ptr<CURL, decltype(&curl_easy_cleanup)> curl(curl_easy_init(), curl_easy_cleanup);

        curl_easy_setopt(curl.get(), CURLOPT_URL, url.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_HTTPHEADER, headers_);
        curl_easy_setopt(curl.get(), CURLOPT_FOLLOWLOCATION, 1L);
        curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, timeoutSeconds);
        curl_easy_setopt(curl.get(), CURLOPT_USERAGENT, "canvas_pdfs/1.0");
        curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION, writer);
        curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, writeTarget);

        if (linkHeader != nullptr) {
            curl_easy_setopt(curl.get(), CURLOPT_HEADERFUNCTION, collectLinkHeader);
            curl_easy_setopt(curl.get(), CURLOPT_HEADERDATA, linkHeader);
        }

        CURLcode result = curl_easy_perform(curl.get());
        curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &status);

        return result;
    }

    Response get(const std::string& url) {
        Response response;
        std::string linkHeader;
        long status = 0;
        CURLcode result = perform(url, appendToString, &response.body, &linkHeader, 60L, status);

        if (result != CURLE_OK) {
            throw std::runtime_error(std::string("rede: ") + curl_easy_strerror(result));
        }

        if (status >= 400) {
            throw HttpError(status, url);
        }

        response.nextUrl = parseNextLink(linkHeader);

        return response;
    }
};

// ---------- Canvas ----------

struct Subject {
    const char* folder;
    const char* searchKey;
};

// searchKey é comparado com o nome da cadeira no Canvas sem acentos e em minúsculas.
const Subject SUBJECTS[] = {
    {"Álgebra Linear", "algebra"},
    {"Sistemas Digitais", "sistemas digitais"},
    {"Fundamentos da Programação", "fundamentos da programacao"},
    {"Análise Matemática", "analise matematica"},
    {"Física", "fisica"},
};

const char* const UNSORTED_FOLDER = "Outros ficheiros";
const char* const RESOURCES_FOLDER = "Recursos da Aula Virtual";
// Os PDFs do próprio módulo; ao lado ficam os Recursos da Aula Virtual e os Resumidos.
const char* const ORIGINALS_FOLDER = "Originais";

struct PdfEntry {
    std::string module;
    Json file;
};

std::string makeSafeName(const std::string& name) {
    std::string cleaned;

    for (char c : name) {
        bool forbidden = std::strchr("\\/:*?\"<>|", c) != nullptr || static_cast<unsigned char>(c) < 0x20;
        cleaned += forbidden ? '_' : c;
    }

    size_t start = cleaned.find_first_not_of(" .");
    size_t end = cleaned.find_last_not_of(" .");

    return start == std::string::npos ? "sem_nome" : cleaned.substr(start, end - start + 1);
}

std::string makeSearchKey(const std::string& text) {
    static const std::vector<std::pair<std::string, char>> accents = {
        {"á", 'a'}, {"à", 'a'}, {"â", 'a'}, {"ã", 'a'}, {"Á", 'a'}, {"À", 'a'}, {"Â", 'a'}, {"Ã", 'a'},
        {"é", 'e'}, {"ê", 'e'}, {"É", 'e'}, {"Ê", 'e'}, {"í", 'i'}, {"Í", 'i'},
        {"ó", 'o'}, {"ô", 'o'}, {"õ", 'o'}, {"Ó", 'o'}, {"Ô", 'o'}, {"Õ", 'o'},
        {"ú", 'u'}, {"ü", 'u'}, {"Ú", 'u'}, {"ç", 'c'}, {"Ç", 'c'},
    };
    std::string key;
    size_t position = 0;

    while (position < text.size()) {
        auto accent = std::find_if(accents.begin(), accents.end(), [&](const auto& pair) {
            return text.compare(position, pair.first.size(), pair.first) == 0;
        });

        if (accent != accents.end()) {
            key += accent->second;
            position += accent->first.size();
        } else {
            key += static_cast<char>(std::tolower(static_cast<unsigned char>(text[position])));
            ++position;
        }
    }

    return key;
}

const std::vector<std::pair<std::string, std::string>>& getAccentCases() {
    static const std::vector<std::pair<std::string, std::string>> cases = {
        {"Á", "á"}, {"À", "à"}, {"Â", "â"}, {"Ã", "ã"}, {"É", "é"}, {"Ê", "ê"}, {"Í", "í"},
        {"Ó", "ó"}, {"Ô", "ô"}, {"Õ", "õ"}, {"Ú", "ú"}, {"Ç", "ç"},
    };

    return cases;
}

// "CÁLCULO DIFERENCIAL EM ℝn" conta como maiúsculas, apesar do "n".
bool isMostlyUppercase(const std::string& text) {
    int upperCount = 0;
    int lowerCount = 0;

    for (const auto& [upper, lower] : getAccentCases()) {
        for (size_t at = text.find(upper); at != std::string::npos; at = text.find(upper, at + 1)) {
            ++upperCount;
        }

        for (size_t at = text.find(lower); at != std::string::npos; at = text.find(lower, at + 1)) {
            ++lowerCount;
        }
    }

    for (unsigned char c : text) {
        upperCount += std::isupper(c) ? 1 : 0;
        lowerCount += std::islower(c) ? 1 : 0;
    }

    return upperCount > lowerCount;
}

// Muda só a primeira letra quando capitalize é true; as restantes ficam em minúsculas.
std::string formatWord(const std::string& word, bool capitalize) {
    std::string result;
    size_t position = 0;

    while (position < word.size()) {
        bool isFirst = position == 0;
        auto accent = std::find_if(getAccentCases().begin(), getAccentCases().end(), [&](const auto& pair) {
            return word.compare(position, pair.first.size(), pair.first) == 0 ||
                   word.compare(position, pair.second.size(), pair.second) == 0;
        });

        if (accent != getAccentCases().end()) {
            result += isFirst && capitalize ? accent->first : accent->second;
            position += accent->first.size();
        } else {
            unsigned char c = static_cast<unsigned char>(word[position]);
            result += static_cast<char>(isFirst && capitalize ? std::toupper(c) : std::tolower(c));
            ++position;
        }
    }

    return result;
}

// "INTRODUÇÃO AO CÁLCULO - LIMITES" -> "Introdução ao Cálculo - Limites"
std::string makeTitleCase(const std::string& text) {
    static const std::set<std::string> smallWords = {
        "a", "o", "as", "os", "e", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
        "ao", "aos", "à", "às", "com", "para", "por", "sem",
    };
    std::istringstream words(text);
    std::string word;
    std::string result;

    while (words >> word) {
        bool isSmall = !result.empty() && smallWords.count(formatWord(word, false)) > 0;
        result += (result.empty() ? "" : " ") + formatWord(word, !isSmall);
    }

    return result;
}

std::string collapseSpaces(const std::string& text) {
    std::istringstream words(text);
    std::string word;
    std::string result;

    while (words >> word) {
        result += (result.empty() ? "" : " ") + word;
    }

    return result;
}

struct ModuleName {
    int number;
    std::string title;
};

// "2. INTRODUÇÃO AO CÁLCULO: LIMITES" -> {2, "Introdução ao Cálculo - Limites"}; sem número, number = -1.
ModuleName parseModuleName(const std::string& name) {
    static const std::regex numbered(R"(^\s*(\d+)\s*[.)-]?\s*(.*)$)");
    std::smatch match;
    int number = -1;
    std::string title = name;

    if (std::regex_match(name, match, numbered) && match[2].length() > 0) {
        number = std::stoi(match[1].str());
        title = match[2].str();
    }

    title = collapseSpaces(std::regex_replace(title, std::regex(R"(\s*:\s*)"), " - "));

    return {number, isMostlyUppercase(title) ? makeTitleCase(title) : title};
}

std::string formatModuleNumber(int number) {
    char buffer[16];
    std::snprintf(buffer, sizeof(buffer), "%02d", number);

    return buffer;
}

bool isResourcesModule(const ModuleName& module) {
    return makeSearchKey(module.title) == makeSearchKey(RESOURCES_FOLDER);
}

// "1. Recursos da Aula Virtual" vai para dentro do módulo 1, se houver um.
std::string buildModuleFolder(const ModuleName& module, const std::vector<ModuleName>& allModules) {
    if (module.number < 0) {
        return makeSafeName(module.title);
    }

    std::string prefix = formatModuleNumber(module.number) + " - ";

    if (!isResourcesModule(module)) {
        return makeSafeName(prefix + module.title) + "/" + ORIGINALS_FOLDER;
    }

    for (const ModuleName& other : allModules) {
        if (other.number == module.number && !isResourcesModule(other)) {
            return makeSafeName(prefix + other.title) + "/" + RESOURCES_FOLDER;
        }
    }

    return makeSafeName(prefix + RESOURCES_FOLDER);
}

// "1_Introdução (1).pdf.pdf" -> "1 - Introdução.pdf"
std::string cleanFileName(const std::string& displayName) {
    std::string stem = std::regex_replace(displayName, std::regex(R"(\s*:\s*)"), " - ");
    std::string extension;
    static const std::regex pdfExtension(R"((\.pdf)+$)", std::regex::icase);

    if (std::regex_search(stem, pdfExtension)) {
        stem = std::regex_replace(stem, pdfExtension, "");
        extension = ".pdf";
    }

    stem = std::regex_replace(stem, std::regex(R"(\s*\(\d+\)$)"), "");
    stem = std::regex_replace(stem, std::regex(R"(^(\d+)_)"), "$1 - ");
    std::replace(stem.begin(), stem.end(), '_', ' ');

    return makeSafeName(collapseSpaces(stem) + extension);
}

const Subject* findSubject(const std::string& courseName) {
    std::string key = makeSearchKey(courseName);

    for (const Subject& subject : SUBJECTS) {
        if (key.find(subject.searchKey) != std::string::npos) {
            return &subject;
        }
    }

    return nullptr;
}

bool isPdf(const Json& file) {
    std::string name = makeSearchKey(file.getString("display_name"));

    return file.getString("content-type") == "application/pdf" ||
           (name.size() >= 4 && name.compare(name.size() - 4, 4, ".pdf") == 0);
}

bool isHiddenFromStudent(const HttpError& error) {
    return error.status == 401 || error.status == 403 || error.status == 404;
}

// Uma área que o docente escondeu (Ficheiros ou Módulos) conta como vazia.
std::vector<Json> fetchVisiblePages(CanvasClient& client, const std::string& path, const std::string& query = "") {
    try {
        return client.fetchAllPages(path, query);
    } catch (const HttpError& error) {
        if (!isHiddenFromStudent(error)) {
            throw;
        }
    }

    return {};
}

std::vector<Json> getModuleItems(CanvasClient& client, const std::string& courseId, const Json& module) {
    const Json* items = module.find("items");

    if (items != nullptr) {
        return items->items;
    }

    // Em módulos com muitos itens o Canvas não os inclui na lista e têm de ser pedidos à parte.
    return fetchVisiblePages(client, "/courses/" + courseId + "/modules/" + module.getString("id") + "/items");
}

std::vector<PdfEntry> listCoursePdfs(CanvasClient& client, const std::string& courseId) {
    std::string coursePath = "/courses/" + courseId;
    std::vector<Json> filesArea = fetchVisiblePages(client, coursePath + "/files", "content_types%5B%5D=application%2Fpdf");
    std::vector<Json> modules = fetchVisiblePages(client, coursePath + "/modules", "include%5B%5D=items");
    std::vector<ModuleName> moduleNames;

    for (const Json& module : modules) {
        moduleNames.push_back(parseModuleName(module.getString("name")));
    }

    std::vector<PdfEntry> found;
    std::vector<std::string> placedIds;

    for (size_t index = 0; index < modules.size(); ++index) {
        const Json& module = modules[index];
        std::string moduleName = buildModuleFolder(moduleNames[index], moduleNames);

        for (const Json& item : getModuleItems(client, courseId, module)) {
            if (item.getString("type") != "File") {
                continue;
            }

            std::string fileId = item.getString("content_id");
            auto known = std::find_if(filesArea.begin(), filesArea.end(),
                                      [&](const Json& file) { return file.getString("id") == fileId; });
            Json file;

            if (known != filesArea.end()) {
                file = *known;
            } else {
                try {
                    file = client.fetchJson(coursePath + "/files/" + fileId);
                } catch (const HttpError&) {
                    // Ficheiro escondido ou bloqueado: segue para o próximo.
                    continue;
                }
            }

            if (isPdf(file)) {
                placedIds.push_back(fileId);
                found.push_back({moduleName, std::move(file)});
            }
        }
    }

    for (Json& file : filesArea) {
        bool isPlaced = std::find(placedIds.begin(), placedIds.end(), file.getString("id")) != placedIds.end();

        if (isPdf(file) && !isPlaced) {
            found.push_back({UNSORTED_FOLDER, std::move(file)});
        }
    }

    return found;
}

// ---------- Programa ----------

struct Options {
    fs::path outputDir = "Faculdade";
    bool includePast = false;
    bool listOnly = false;
};

Options parseArguments(int argc, char** argv) {
    Options options;

    for (int i = 1; i < argc; ++i) {
        std::string argument = argv[i];

        if (argument == "--saida" && i + 1 < argc) {
            options.outputDir = argv[++i];
        } else if (argument == "--todas") {
            options.includePast = true;
        } else if (argument == "--listar") {
            options.listOnly = true;
        } else {
            std::cout << "Uso: " << argv[0] << " [--saida PASTA] [--todas] [--listar]\n";
            std::exit(argument == "-h" || argument == "--help" ? 0 : 2);
        }
    }

    return options;
}

int main(int argc, char** argv) {
    // Sem terminal (Docker, segundo plano) o cout só escreveria no fim; assim cada linha sai logo.
    std::cout << std::unitbuf;

    Options options = parseArguments(argc, argv);
    const char* urlVariable = std::getenv("CANVAS_URL");
    const char* tokenVariable = std::getenv("CANVAS_TOKEN");
    std::string baseUrl = urlVariable ? urlVariable : DEFAULT_CANVAS_URL;
    std::string token = tokenVariable ? tokenVariable : "";

    while (!baseUrl.empty() && baseUrl.back() == '/') {
        baseUrl.pop_back();
    }

    if (token.empty()) {
        std::cerr << "Define CANVAS_TOKEN (vê as instruções no topo do ficheiro).\n";

        return 1;
    }

    curl_global_init(CURL_GLOBAL_DEFAULT);
    CanvasClient client(baseUrl, token);
    std::vector<Json> courses;

    try {
        courses = client.fetchAllPages("/courses", options.includePast ? "" : "enrollment_state=active");
    } catch (const HttpError& error) {
        std::cerr << "O Canvas recusou o pedido (" << error.status << "). Confirma o token.\n";

        return 1;
    } catch (const std::exception& error) {
        std::cerr << "Erro: " << error.what() << "\n";

        return 1;
    }

    int downloaded = 0;
    int skipped = 0;
    int failed = 0;
    int matchedCourses = 0;

    for (const Json& course : courses) {
        std::string courseName = course.getString("name");
        const Subject* subject = findSubject(courseName);

        if (subject == nullptr) {
            continue;
        }

        ++matchedCourses;
        std::cout << "\n== " << subject->folder << "  (" << courseName << ")\n";
        std::vector<PdfEntry> pdfs;

        try {
            pdfs = listCoursePdfs(client, course.getString("id"));
        } catch (const std::exception& error) {
            std::cout << "   sem acesso aos ficheiros (" << error.what() << ")\n";
            continue;
        }

        if (pdfs.empty()) {
            std::cout << "   nenhum PDF\n";
            continue;
        }

        fs::path subjectDir = options.outputDir / subject->folder;
        std::set<fs::path> usedPaths;

        for (const PdfEntry& entry : pdfs) {
            std::string displayName = entry.file.getString("display_name");
            std::string name = cleanFileName(displayName.empty() ? entry.file.getString("filename") : displayName);
            fs::path destination = subjectDir / entry.module / name;

            // A limpeza pode dar o mesmo nome a dois ficheiros diferentes ("x.pdf" e "x (1).pdf").
            fs::path original = destination;

            for (int copy = 2; usedPaths.count(destination) > 0; ++copy) {
                name = original.stem().string() + " (" + std::to_string(copy) + ")" + original.extension().string();
                destination = original.parent_path() / name;
            }

            usedPaths.insert(destination);
            std::string label = entry.module + "/" + name;

            if (options.listOnly) {
                std::cout << "   " << label << "\n";
                continue;
            }

            std::string url = entry.file.getString("url");

            if (entry.file.getBool("locked_for_user") || url.empty()) {
                std::cout << "   bloqueado: " << label << "\n";
                ++failed;
                continue;
            }

            std::string expectedSize = entry.file.getString("size");
            std::error_code ignored;

            if (fs::exists(destination) && std::to_string(fs::file_size(destination, ignored)) == expectedSize) {
                ++skipped;
                continue;
            }

            try {
                fs::create_directories(destination.parent_path());
                client.downloadTo(url, destination);
                std::cout << "   ok: " << label << "\n";
                ++downloaded;
            } catch (const std::exception& error) {
                std::cout << "   erro: " << label << " (" << error.what() << ")\n";
                ++failed;
            }
        }
    }

    curl_global_cleanup();

    if (matchedCourses == 0) {
        std::cerr << "Nenhuma das disciplinas foi encontrada no Canvas.\n";

        return 1;
    }

    if (!options.listOnly) {
        std::cout << "\nDescarregados: " << downloaded << " · já existiam: " << skipped << " · falharam: " << failed
                  << "\nPasta: " << fs::absolute(options.outputDir).string() << "\n";
    }

    return failed > 0 ? 1 : 0;
}
