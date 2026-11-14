# SPOT 배포용 (Render 무료 웹 서비스, 메모리 512MB)
FROM python:3.12-slim

# root가 아닌 사용자로 실행한다
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user app ./app
COPY --chown=user data ./data
COPY --chown=user web ./web

# 임베딩 모델을 이미지에 미리 넣어 둔다 (첫 요청이 느려지지 않게)
RUN python -c "from app.services.embedder import _load; _load()"
# 실행 중에는 Hugging Face에 접속하지 않고 이미지 안의 모델만 쓴다
ENV HF_HUB_OFFLINE=1

# Render는 PORT 환경변수로 포트를 알려 준다. 없으면 7860.
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
