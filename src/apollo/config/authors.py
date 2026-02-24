"""
Curated list of high-impact AI researchers.
Names are matched (case-insensitive substring) against paper author lists.
Boost weight is added per matched author in Layer 2 filtering.
Edit freely — add/remove researchers as the field evolves.
"""

# Each entry: (display_name, boost_weight)
# boost_weight defaults to settings.AUTHOR_BOOST_PER_MATCH if set to None
HIGH_IMPACT_AUTHORS: list[tuple[str, int | None]] = [
    # Deep Learning Pioneers
    ("Yann LeCun", None),
    ("Yoshua Bengio", None),
    ("Geoffrey Hinton", None),

    # OpenAI / Former OpenAI
    ("Ilya Sutskever", None),
    ("Andrej Karpathy", None),
    ("John Schulman", None),
    ("Paul Christiano", None),
    ("Alec Radford", None),

    # DeepMind / Google
    ("Demis Hassabis", None),
    ("David Silver", None),
    ("Oriol Vinyals", None),
    ("Jeff Dean", None),
    ("Quoc Le", None),
    ("Noam Shazeer", None),
    ("Samy Bengio", None),

    # Berkeley / Stanford / CMU
    ("Pieter Abbeel", None),
    ("Sergey Levine", None),
    ("Chelsea Finn", None),
    ("Percy Liang", None),
    ("Christopher Manning", None),
    ("Fei-Fei Li", None),
    ("Jure Leskovec", None),
    ("Ruslan Salakhutdinov", None),
    ("Tom Mitchell", None),

    # Transformers / Attention
    ("Ashish Vaswani", None),
    ("Jakob Uszkoreit", None),
    ("Llion Jones", None),

    # Diffusion / Generative
    ("Yang Song", None),
    ("Prafulla Dhariwal", None),
    ("Alex Nichol", None),
    ("Jonathan Ho", None),

    # RLHF / Alignment
    ("Jan Leike", None),
    ("Ziegler", None),          # Daniel Ziegler

    # Agents / RAG / Memory
    ("Harrison Chase", None),   # LangChain
    ("Langchain", None),
    ("Omar Khattab", None),     # DSPy / ColBERT

    # Meta AI
    ("Yann Dauphin", None),
    ("Luke Zettlemoyer", None),
    ("Mike Lewis", None),
    ("Tim Dettmers", None),

    # Mistral / Open-source LLMs
    ("Guillaume Lample", None),
    ("Alexandre Sablayrolles", None),
]


def get_author_lookup() -> dict[str, int]:
    """
    Returns a dict mapping lowercase author name → boost weight.
    Used by filters.py for O(1) lookups.
    """
    from apollo.config.settings import AUTHOR_BOOST_PER_MATCH
    return {
        name.lower(): (weight if weight is not None else AUTHOR_BOOST_PER_MATCH)
        for name, weight in HIGH_IMPACT_AUTHORS
    }
