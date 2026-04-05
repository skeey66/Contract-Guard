from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    # Ollama 설정
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_name: str = "qwen3:8b"
    ollama_timeout: int = 180

    # 임베딩 모델
    embedding_model: str = "jhgan/ko-sroberta-multitask"
    embedding_device: str = "auto"

    # ChromaDB 설정
    chroma_persist_dir: str = str(DATA_DIR / "chroma")
    chroma_collection: str = "contract_kb"

    # 탐지 설정
    rule_score_threshold: float = 0.3
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.5

    # 파일 경로
    upload_dir: str = str(DATA_DIR / "uploads")
    documents_dir: str = str(DATA_DIR / "documents")
    results_dir: str = str(DATA_DIR / "results")

    model_config = {"env_file": str(BASE_DIR / ".env"), "extra": "ignore"}


settings = Settings()
