"""
Jarvis Memory — SQLite episodic + optional FAISS vector memory.
"""
import json
import logging

from app import db

logger = logging.getLogger("Jarvis")


class EpisodicMemory:
    """SQLite-backed episodic memory (replaces JSON file)."""

    @staticmethod
    def save(event_type: str, content: dict) -> str:
        return db.save_episodic_event(event_type, content)

    @staticmethod
    def recall(event_type: str = None, limit: int = 50) -> list:
        events = db.get_episodic_events(event_type=event_type, limit=limit)
        result = []
        for e in events:
            entry = {
                "id": e["id"],
                "event_type": e["event_type"],
                "timestamp": e["timestamp"],
            }
            try:
                entry["content"] = json.loads(e["content_json"])
            except (json.JSONDecodeError, TypeError):
                entry["content"] = e["content_json"]
            result.append(entry)
        return result


class VectorMemory:
    """
    Optional FAISS-backed vector memory for semantic search.
    Gracefully degrades if FAISS/sentence-transformers are not installed.
    """

    def __init__(self):
        self._index = None
        self._model = None
        self._documents = []
        self._available = False
        self._init()

    def _init(self):
        try:
            import faiss
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            self._dimension = 384  # all-MiniLM-L6-v2 output dimension
            self._index = faiss.IndexFlatL2(self._dimension)
            self._available = True
            logger.info("Vector memory initialized with FAISS + sentence-transformers.")
        except ImportError:
            logger.info("FAISS/sentence-transformers not installed. Vector memory disabled.")
            self._available = False

    @property
    def is_available(self) -> bool:
        return self._available

    def add(self, text: str, metadata: dict = None):
        if not self._available:
            return
        import numpy as np
        embedding = self._model.encode([text])
        self._index.add(np.array(embedding, dtype="float32"))
        self._documents.append({"text": text, "metadata": metadata or {}})

    def search(self, query: str, top_k: int = 5) -> list:
        if not self._available or self._index.ntotal == 0:
            return []
        import numpy as np
        query_embedding = self._model.encode([query])
        distances, indices = self._index.search(
            np.array(query_embedding, dtype="float32"), min(top_k, self._index.ntotal)
        )
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self._documents):
                results.append({
                    "text": self._documents[idx]["text"],
                    "metadata": self._documents[idx]["metadata"],
                    "distance": float(distances[0][i]),
                })
        return results


# Singletons
episodic_memory = EpisodicMemory()
vector_memory = VectorMemory()
