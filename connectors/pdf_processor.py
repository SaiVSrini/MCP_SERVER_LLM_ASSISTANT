from typing import Dict, Optional
from PyPDF2 import PdfReader
from io import BytesIO
import base64

class PDFProcessor:
    """PDF document processor with privacy protection."""
    
    def __init__(self, cfg: Optional[Dict] = None, llm=None):
        self.cfg = cfg or {}
        self.llm = llm

    def _extract_text(self, pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes."""
        try:
            pdf = PdfReader(BytesIO(pdf_bytes))
            text = ""
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + ("\n" if page_text else "")
            return text
        except Exception as e:
            print(f"PDF extraction error: {e}")
            return ""

    def process(self, pdf_data: str) -> Dict:
        """Process PDF content with privacy protection."""
        try:
            pdf_bytes = base64.b64decode(pdf_data)
            
            raw_text = self._extract_text(pdf_bytes)

            redacted_text = raw_text
            if self.llm and raw_text:
                redacted_text = self.llm._redact_sensitive_info(raw_text)

            return {
                "text": redacted_text,
                "raw_text": raw_text,
                "status": "success",
                "length": len(redacted_text)
            }
        except Exception as e:
            return {
                "error": str(e),
                "status": "failed"
            }
