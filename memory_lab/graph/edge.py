from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    from_node: str
    relation: str
    to_node: str
    source_id: str
    confidence: float = 0.9

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0,1], got {self.confidence}")
