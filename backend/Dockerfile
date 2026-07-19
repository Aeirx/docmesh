FROM python:3.11-slim

WORKDIR /app

# Install deps first so source edits don't bust the pip layer cache.
#
# --extra-index-url https://download.pytorch.org/whl/cpu is load-bearing on
# Linux: plain `pip install torch` from PyPI pulls the CUDA build (~5 GB of
# NVIDIA wheels) for a CPU-only app. The +cpu local version sorts higher than
# the PyPI 2.6.0, so pip picks the CPU wheel; on Windows/local venvs the PyPI
# torch is already CPU-only, which is why the flag lives here and not in
# requirements.txt. (llama-cpp-python's own CPU wheel index is already inline
# in requirements.txt and ships manylinux wheels — no compiler needed.)
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.txt

COPY pyproject.toml alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# Model caches live under the mounted ./data volume so container recreation
# never re-downloads: HF_HOME covers bge + the cross-encoder; the Qwen GGUF
# already goes to data/models/ via settings.
ENV HF_HOME=/app/data/hf

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
