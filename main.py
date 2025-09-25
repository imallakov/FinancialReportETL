import os
import json
import requests
from datetime import datetime
import pdfplumber
import re

# Configuration
INPUT_PDF_PATH = "Amazon-2024-Annual-Report.pdf"
OUTPUT_BASE_DIR = "financial_report_output"
DEEPSEEK_API_KEY = "sk-2b38bca44435476786d9de8c923817bf"  # Replace with your actual API key
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Pre-filter keywords and patterns for financial tables
FINANCIAL_KEYWORDS = [
    # Financial statements
    'balance sheet', 'income statement', 'cash flow', 'statement of operations',
    'consolidated balance', 'consolidated statements', 'financial position',
    'statement of financial', 'statement of cash', 'statement of income',

    # Financial metrics
    'revenue', 'sales', 'income', 'profit', 'loss', 'earnings', 'expenses',
    'assets', 'liabilities', 'equity', 'cash', 'debt', 'ebitda', 'eps',
    'gross profit', 'operating income', 'net income', 'total assets',
    'total liabilities', 'shareholders equity', 'retained earnings',
    'accounts receivable', 'inventory', 'property and equipment',
    'accounts payable', 'long-term debt', 'common stock',

    # Accounting periods
    'fiscal year', 'quarter ended', 'year ended', 'three months', 'twelve months',
    'fiscal 2024', 'fiscal 2023', 'fiscal 2022',

    # Financial sections
    'financial statements', 'notes to financial statements', 'audit report',
]

FINANCIAL_SYMBOLS = ['$', '€', '£', '¥', 'USD', 'EUR', 'GBP']

# Table structure patterns
TABLE_PATTERNS = [
    r'\b(20\d{2}\s+){2,}20\d{2}\b',  # Year sequences: 2023 2022 2021
    r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?',  # Currency amounts: $1,000.00
    r'\d{1,3}(?:,\d{3})+(?:\.\d{2})?',  # Large numbers: 1,000,000.00
    r'\(\d{1,3}(?:,\d{3})*(?:\.\d{2})?\)',  # Negative numbers in parentheses
    r'\b\d+\.\d{2}\b',  # Decimal numbers: 123.45
]


def setup_directories():
    """Create necessary output directories"""
    dirs = [
        OUTPUT_BASE_DIR,
        os.path.join(OUTPUT_BASE_DIR, "financial_pages"),
        os.path.join(OUTPUT_BASE_DIR, "api_logs"),
        os.path.join(OUTPUT_BASE_DIR, "prefilter_logs")
    ]

    for dir_path in dirs:
        os.makedirs(dir_path, exist_ok=True)

    return dirs


def extract_text_with_pdfplumber(page):
    """Extract text from page with layout preservation"""
    try:
        text = page.extract_text(
            layout=True,  # Preserve layout and spacing
            x_tolerance=3,
            y_tolerance=3,
            use_text_flow=True
        )
        return text.strip() if text else ""
    except Exception as e:
        print(f"Text extraction error: {e}")
        return ""


def pre_filter_financial_page(page_text, page_number):
    """Pre-filter pages using keywords and patterns before API call"""

    if not page_text or len(page_text.strip()) < 100:
        return False, 0.0, "Insufficient text content"

    text_lower = page_text.lower()
    prefilter_score = 0.0
    reasons = []

    # 1. Check for financial keywords (strong indicator)
    keyword_matches = []
    for keyword in FINANCIAL_KEYWORDS:
        if keyword.lower() in text_lower:
            keyword_matches.append(keyword)

    if keyword_matches:
        keyword_score = min(1.0, len(keyword_matches) * 0.3)
        prefilter_score += keyword_score
        reasons.append(f"{len(keyword_matches)} financial keywords")

    # 2. Check for financial symbols (medium indicator)
    symbol_matches = []
    for symbol in FINANCIAL_SYMBOLS:
        if symbol in page_text:
            symbol_matches.append(symbol)

    if symbol_matches:
        symbol_score = min(0.4, len(symbol_matches) * 0.2)
        prefilter_score += symbol_score
        reasons.append(f"{len(symbol_matches)} currency symbols")

    # 3. Check for table structure patterns (strong indicator)
    pattern_matches = 0
    for pattern in TABLE_PATTERNS:
        matches = re.findall(pattern, page_text)
        pattern_matches += len(matches)

    if pattern_matches > 0:
        pattern_score = min(0.6, (pattern_matches / 5) * 0.6)
        prefilter_score += pattern_score
        reasons.append(f"{pattern_matches} table patterns")

    # 4. Check for tabular structure (rows with multiple numbers)
    lines = page_text.split('\n')
    table_like_lines = 0

    for line in lines:
        line = line.strip()
        if len(line) > 20:  # Reasonable line length for table rows
            # Count numbers and check for alignment indicators
            numbers = re.findall(r'\d+[,.]?\d*', line)
            has_multiple_numbers = len(numbers) >= 3
            has_currency = any(symbol in line for symbol in FINANCIAL_SYMBOLS)
            has_year_sequence = bool(re.search(r'(20\d{2}\s+){2,}20\d{2}', line))

            if has_multiple_numbers or has_currency or has_year_sequence:
                table_like_lines += 1

    if table_like_lines >= 3:  # At least 3 table-like lines
        structure_score = min(0.5, (table_like_lines / 10) * 0.5)
        prefilter_score += structure_score
        reasons.append(f"{table_like_lines} table-like lines")

    # Determine if page passes pre-filter
    passes_prefilter = prefilter_score >= 0.4
    reason_text = " | ".join(reasons) if reasons else "No strong indicators"

    # Log pre-filter results
    log_prefilter_result(page_number, page_text, prefilter_score, passes_prefilter, reasons)

    return passes_prefilter, prefilter_score, reason_text


def log_prefilter_result(page_number, page_text, score, passed, reasons):
    """Log pre-filter results for analysis"""
    log_dir = os.path.join(OUTPUT_BASE_DIR, "prefilter_logs")
    os.makedirs(log_dir, exist_ok=True)

    log_entry = {
        "page_number": page_number,
        "timestamp": datetime.now().isoformat(),
        "prefilter_score": score,
        "passed_prefilter": passed,
        "reasons": reasons,
        "text_preview": page_text[:500] + "..." if len(page_text) > 500 else page_text,
        "text_length": len(page_text)
    }

    log_file = os.path.join(log_dir, f"page_{page_number}_prefilter.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)


def check_financial_table_with_deepseek(page_text, page_number):
    """Use DeepSeek API to check if page contains financial data tables"""

    prompt = f"""
    Analyze the following text extracted from page {page_number} of a financial report. 
    Determine if this page contains financial data tables (balance sheet, income statement, cash flow statement, etc.).

    CRITERIA for financial data tables:
    - Contains structured financial data with rows and columns
    - Has financial metrics like revenue, assets, liabilities, equity, etc.
    - Shows numerical data in tabular format
    - May include year-over-year comparisons (2023, 2022, 2021)
    - Typically has currency symbols and amounts

    Respond with JSON format only:
    {{
        "contains_financial_tables": true/false,
        "confidence": 0.0-1.0,
        "reason": "brief explanation",
        "table_types": ["balance_sheet", "income_statement", "cash_flow", "other"] or []
    }}

    Page text:
    {page_text[:8000]}  # Conservative limit to avoid token issues
    """

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a financial analyst expert. Analyze text for financial data tables and respond with JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 500
        }

        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        api_response = result["choices"][0]["message"]["content"].strip()

        # Clean the response - remove markdown code blocks if present
        api_response_clean = api_response.replace("```json", "").replace("```", "").strip()

        # Parse JSON response
        analysis_result = json.loads(api_response_clean)

        # Log the API call
        log_api_call(page_number, prompt, api_response_clean, analysis_result)

        return (analysis_result["contains_financial_tables"],
                analysis_result.get("confidence", 0.0),
                analysis_result.get("reason", "No reason provided"))

    except Exception as e:
        print(f"DeepSeek API error for page {page_number}: {e}")
        # Fallback: log the error and return false
        log_api_error(page_number, str(e), prompt)
        return False, 0.0, f"API error: {e}"


def log_api_call(page_number, prompt, response, result):
    """Log API requests and responses for debugging"""
    log_dir = os.path.join(OUTPUT_BASE_DIR, "api_logs")
    os.makedirs(log_dir, exist_ok=True)

    log_entry = {
        "page_number": page_number,
        "timestamp": datetime.now().isoformat(),
        "prompt_length": len(prompt),
        "response": response,
        "result": result
    }

    log_file = os.path.join(log_dir, f"page_{page_number}_api_log.json")
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)


def log_api_error(page_number, error, prompt):
    """Log API errors for debugging"""
    log_dir = os.path.join(OUTPUT_BASE_DIR, "api_logs")
    os.makedirs(log_dir, exist_ok=True)

    error_entry = {
        "page_number": page_number,
        "timestamp": datetime.now().isoformat(),
        "error": error,
        "prompt_preview": prompt[:500] + "..." if len(prompt) > 500 else prompt
    }

    error_file = os.path.join(log_dir, f"page_{page_number}_api_error.json")
    with open(error_file, "w", encoding="utf-8") as f:
        json.dump(error_entry, f, indent=2, ensure_ascii=False)


def save_financial_page(page_text, page_number, confidence, reason, prefilter_score):
    """Save financial page text with metadata"""
    financial_dir = os.path.join(OUTPUT_BASE_DIR, "financial_pages")

    # Create page-specific directory
    page_dir = os.path.join(financial_dir, f"page_{page_number}")
    os.makedirs(page_dir, exist_ok=True)

    # Save full text with original spacing
    text_file = os.path.join(page_dir, "full_text.txt")
    with open(text_file, "w", encoding="utf-8") as f:
        f.write(page_text)

    # Save metadata
    metadata = {
        "page_number": page_number,
        "extraction_date": datetime.now().isoformat(),
        "ai_confidence": confidence,
        "prefilter_score": prefilter_score,
        "classification_reason": reason,
        "text_length": len(page_text),
        "has_financial_tables": True
    }

    meta_file = os.path.join(page_dir, "metadata.json")
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"✅ Page {page_number}: Saved (AI confidence: {confidence:.2f}, Pre-filter: {prefilter_score:.2f})")


def process_pdf_with_prefilter(pdf_path):
    """Process PDF with pre-filtering and DeepSeek API validation"""
    financial_pages = []
    api_calls_saved = 0
    total_pages_processed = 0

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)
        print(f"Processing PDF with {total_pages} pages (pre-filter + DeepSeek)...")

        for page_num, page in enumerate(pdf.pages, 1):
            try:
                total_pages_processed += 1
                print(f"📄 Processing page {page_num}/{total_pages}...")

                # Extract text with proper spacing
                page_text = extract_text_with_pdfplumber(page)

                if not page_text or len(page_text.strip()) < 100:
                    print(f"⏭️  Page {page_num}: Insufficient text, skipping")
                    continue

                # Step 1: Pre-filter with keywords/patterns
                passes_prefilter, prefilter_score, prefilter_reason = pre_filter_financial_page(
                    page_text, page_num
                )

                if not passes_prefilter:
                    print(f"🚫 Page {page_num}: Failed pre-filter (score: {prefilter_score:.2f})")
                    api_calls_saved += 1
                    continue

                print(f"🔍 Page {page_num}: Passed pre-filter (score: {prefilter_score:.2f}), sending to DeepSeek...")

                # Step 2: Use DeepSeek API for final validation
                has_financial_tables, confidence, reason = check_financial_table_with_deepseek(
                    page_text, page_num
                )

                if has_financial_tables and confidence > 0.7:
                    # Save the financial page
                    save_financial_page(page_text, page_num, confidence, reason, prefilter_score)
                    financial_pages.append({
                        "page_number": page_num,
                        "ai_confidence": confidence,
                        "prefilter_score": prefilter_score,
                        "reason": reason,
                        "text_length": len(page_text)
                    })
                    print(f"💰 Page {page_num}: Financial tables confirmed!")
                else:
                    print(f"❌ Page {page_num}: AI rejected (confidence: {confidence:.2f})")

                # Add small delay to avoid rate limiting
                import time
                time.sleep(1)

            except Exception as e:
                print(f"❌ Error processing page {page_num}: {e}")
                continue

    return financial_pages, api_calls_saved, total_pages_processed


def main():
    print("Starting AI-powered financial PDF processing with pre-filtering...")
    setup_directories()

    try:
        # Process PDF with pre-filtering and API validation
        financial_pages, api_calls_saved, total_processed = process_pdf_with_prefilter(INPUT_PDF_PATH)

        # Save comprehensive summary
        summary = {
            "processing_date": datetime.now().isoformat(),
            "input_file": INPUT_PDF_PATH,
            "total_pages_processed": total_processed,
            "financial_pages_found": len(financial_pages),
            "api_calls_saved": api_calls_saved,
            "efficiency_improvement": f"{(api_calls_saved / total_processed) * 100:.1f}%",
            "financial_page_numbers": [p["page_number"] for p in financial_pages],
            "average_ai_confidence": sum(p["ai_confidence"] for p in financial_pages) / len(
                financial_pages) if financial_pages else 0,
            "average_prefilter_score": sum(p["prefilter_score"] for p in financial_pages) / len(
                financial_pages) if financial_pages else 0,
            "method": "prefilter_deepseek_hybrid"
        }

        summary_file = os.path.join(OUTPUT_BASE_DIR, "processing_summary.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"\n🎉 Processing complete!")
        print(f"📊 Summary:")
        print(f"   • Total pages processed: {total_processed}")
        print(f"   • Financial pages found: {len(financial_pages)}")
        print(f"   • API calls saved: {api_calls_saved} (efficiency: {summary['efficiency_improvement']})")
        print(f"   • Pages saved: {[p['page_number'] for p in financial_pages]}")
        print(f"   • Output location: {OUTPUT_BASE_DIR}")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
