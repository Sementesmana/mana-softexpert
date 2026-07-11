"""mana-softexpert — SDK Camada 2A de ESCRITA no SoftExpert Workflow (Maná Builder).

>>> from mana_softexpert import SoftExpertWF, SoftExpertError
"""
from .wf import SoftExpertError, SoftExpertWF

__all__ = ["SoftExpertWF", "SoftExpertError"]
__version__ = "0.1.0"
