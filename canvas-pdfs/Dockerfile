# Compila numa imagem com as ferramentas e copia só o executável para uma imagem pequena.
FROM debian:bookworm-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends g++ libcurl4-openssl-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY canvas_pdfs.cpp .
RUN g++ -std=c++17 -O2 -Wall canvas_pdfs.cpp -lcurl -o canvas_pdfs

FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libcurl4 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/canvas_pdfs /usr/local/bin/canvas_pdfs
# Os PDFs vão para /dados; monta lá uma pasta do teu computador (-v).
WORKDIR /dados
ENTRYPOINT ["canvas_pdfs", "--saida", "/dados"]
