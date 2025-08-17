# cpe_parser/values/relation.py
import enum

class Relation(enum.Enum):
    DISJOINT = "DISJOINT"
    EQUAL = "EQUAL"
    SUBSET = "SUBSET"
    SUPERSET = "SUPERSET"