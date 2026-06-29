FROM python:3.11-slim
RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g; \
            s|http://security.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' \
    /etc/apt/sources.list.d/debian.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice \
        pandoc \
        fontconfig \
        fonts-noto-cjk \
        fonts-wqy-zenhei \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.minimal.txt .
RUN pip install --no-cache-dir -r requirements.minimal.txt

COPY . .

RUN mkdir -p /usr/local/share/fonts/custom \
    && cp -r /app/Fonts/* /usr/local/share/fonts/custom/ || true \
    && find /usr/local/share/fonts/custom -type f \
        \( -iname "*.fon" -o -iname "*.fnt" \) -delete \
    && fc-cache -f -v

RUN mkdir -p Datas logs html

ENV DOC_PARSER_HOST=0.0.0.0 \
    DOC_PARSER_PORT=18201 \
    DOC_PARSER_SHARE_DIR=/app/Datas

EXPOSE 18201

CMD ["python", "main.py"]
