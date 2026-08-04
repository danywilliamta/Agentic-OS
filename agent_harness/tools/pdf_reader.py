"""
PDF Reader Tool - Extract text content from PDF files.
"""

import os
from typing import Dict, Any
from agent_harness.tool_registry import tool_registry


@tool_registry.register(category="document")
def read_pdf(
    file_path: str,
    base_path: str = ""
) -> Dict[str, Any]:
    """
    Read and extract text content from a PDF file or text file.

    Args:
        file_path: Path to the PDF or TXT file to read
        base_path: Optional base directory to prepend to file_path

    Returns:
        Dict with extracted text content or error
    """
    try:
        # Combine base_path with file_path if provided
        if base_path:
            full_path = os.path.join(base_path, file_path)
        else:
            full_path = file_path
        # Check if it's a plain text file first
        if full_path.lower().endswith('.txt'):
            with open(full_path, 'r', encoding='utf-8') as file:
                content = file.read()

                return {
                    "success": True,
                    "content": content,
                    "pages": 1,
                    "file_path": full_path,
                    "error": None
                }

        # Otherwise, process as PDF
        # Try PyPDF2 first (simple, no dependencies)
        try:
            import PyPDF2

            with open(full_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text_content = []

                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text_content.append(page.extract_text())

                full_text = "\n\n".join(text_content)

                return {
                    "success": True,
                    "content": full_text,
                    "pages": len(pdf_reader.pages),
                    "file_path": full_path,
                    "error": None
                }

        except ImportError:
            # Fallback to pdfplumber if available
            import pdfplumber

            with pdfplumber.open(full_path) as pdf:
                text_content = []

                for page in pdf.pages:
                    text_content.append(page.extract_text())

                full_text = "\n\n".join(text_content)

                return {
                    "success": True,
                    "content": full_text,
                    "pages": len(pdf.pages),
                    "file_path": full_path,
                    "error": None
                }

    except FileNotFoundError:
        return {
            "success": False,
            "content": None,
            "error": f"File not found: {full_path}"
        }

    except Exception as e:
        return {
            "success": False,
            "content": None,
            "error": f"Error reading PDF: {str(e)}"
        }
