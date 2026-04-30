from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    # Ollama 설정
    ollama_base_url: str = "http://localhost:11434"
    ollama_model_name: str = "exaone3.5:7.8b"
    ollama_timeout: int = 180

    # 임베딩 모델 — BAAI/bge-m3: 8192 토큰 컨텍스트, 1024차원, 다국어 지원
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "auto"

    # Reranker — bge-m3와 호환되는 cross-encoder. 1차 hybrid retrieval 풀을 정밀 재정렬.
    # 기본 비활성화 — 12GB VRAM에서 EXAONE+bge-m3와 병행 시 GPU swap 또는 CPU rerank 비용
    # 으로 검증/분석 시간이 5-10배 증가. 정확도 향상 +1~3%p 대비 비용 큼. 필요 시 toggle.
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_max_length: int = 512
    reranker_device: str = "cpu"

    # ChromaDB 설정
    chroma_persist_dir: str = str(DATA_DIR / "chroma")
    chroma_collection: str = "contract_kb"

    # 탐지 설정
    rule_score_threshold: float = 0.3
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.5

    # 파일 경로
    upload_dir: str = str(DATA_DIR / "uploads")
    documents_dir: str = str(DATA_DIR / "documents")
    results_dir: str = str(DATA_DIR / "results")

    model_config = {"env_file": str(BASE_DIR / ".env"), "extra": "ignore"}


settings = Settings()
