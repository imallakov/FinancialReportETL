import pdfplumber
import pandas as pd
import os
import re
from collections import defaultdict


def remove_internal_commas(text):
    """Remove commas from text to prevent CSV issues"""
    if text is None:
        return ""
    return re.sub(r',', '', str(text).strip())


def get_text_positions(page):
    """Extract text elements with their x-coordinates (horizontal positions)"""
    words = page.extract_words(use_text_flow=True)
    # Return list of (x1 coordinate, text) sorted by vertical position (top)
    return sorted([(word['x1'], word['text']) for word in words], key=lambda x: x[0])


def detect_column_boundaries(text_positions, min_gap=10):
    """Detect column boundaries using gaps between text x-positions"""
    if not text_positions:
        return []

    # Get all unique x positions
    x_positions = sorted(list(set([x for x, _ in text_positions])))

    # Find significant gaps between x positions (indicates column boundaries)
    gaps = []
    for i in range(1, len(x_positions)):
        gap = x_positions[i] - x_positions[i - 1]
        if gap > min_gap:  # Adjust min_gap based on your PDF's spacing
            gaps.append((x_positions[i - 1], x_positions[i], gap))

    # Sort gaps by size (largest first) to find major column divisions
    gaps.sort(key=lambda x: x[2], reverse=True)

    # Take top gaps as column boundaries (adjust number based on typical table complexity)
    num_columns = min(6, len(gaps) + 1)  # Assume max 6 columns for financial reports
    boundaries = [0]  # Start from left edge
    for i in range(num_columns - 1):
        if i < len(gaps):
            boundaries.append((gaps[i][0] + gaps[i][1]) / 2)  # Midpoint of gap
    boundaries.append(max(x_positions) + 10)  # Right edge

    return sorted(boundaries)


def extract_spaced_table(page, min_gap=10):
    """Extract tables that use whitespace instead of lines to separate columns"""
    # Get all text with vertical positions (to group into rows)
    words = page.extract_words(use_text_flow=True)
    if not words:
        return []

    # Group words into rows based on vertical position (top coordinate)
    rows = defaultdict(list)
    for word in words:
        # Round top position to group words in the same row (adjust tolerance as needed)
        row_key = round(word['top'], 1)
        rows[row_key].append((word['x1'], word['text']))  # (x position, text)

    # Sort rows by vertical position (top to bottom)
    sorted_rows = sorted(rows.items(), key=lambda x: x[0])

    # Extract text positions to detect columns
    all_text_positions = [(x, text) for _, row in sorted_rows for x, text in row]
    columns = detect_column_boundaries(all_text_positions, min_gap)

    # Build table by assigning words to columns based on x position
    table = []
    for _, row_words in sorted_rows:
        row = [""] * len(columns)
        for x, text in row_words:
            # Find which column this word belongs to
            for col_idx, boundary in enumerate(columns[1:]):
                if x <= boundary:
                    row[col_idx] += f" {text}"  # Combine words in the same column
                    break
        # Clean up extra spaces
        row = [remove_internal_commas(cell.strip()) for cell in row]
        table.append(row)

    return table


def extract_tables_from_pdf(pdf_path, output_folder="extracted_tables", min_gap=10):
    """Extract tables (including spaced-column tables) and save as CSV"""
    os.makedirs(output_folder, exist_ok=True)
    table_count = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            print(f"Processing page {page_num}...")

            # First try standard table extraction (for tables with lines)
            standard_tables = page.extract_tables(table_settings={
                "vertical_strategy": "text",  # Use text positions instead of lines
                "horizontal_strategy": "text",
                "snap_tolerance": 5,
                "join_tolerance": 3
            })

            # Process standard tables if any
            for table in standard_tables:
                if table and any(table):
                    table_count += 1
                    # Clean commas
                    cleaned_table = [[remove_internal_commas(cell) for cell in row] for row in table]
                    # Create DataFrame
                    headers = cleaned_table[0] if any(cleaned_table[0]) else [f"Col_{i}" for i in
                                                                              range(len(cleaned_table[0]))]
                    df = pd.DataFrame(cleaned_table[1:], columns=headers).dropna(how="all")
                    # Save
                    df.to_csv(f"{output_folder}/table_page_{page_num}_std_{table_count}.csv", index=False)
                    print(f"Saved standard table {table_count} from page {page_num}")

            # Extract spaced-column tables (no lines)
            spaced_table = extract_spaced_table(page, min_gap)
            if spaced_table and len(spaced_table) > 1 and any(len(cell) > 0 for row in spaced_table for cell in row):
                table_count += 1
                # Create DataFrame
                headers = spaced_table[0] if any(spaced_table[0]) else [f"Col_{i}" for i in range(len(spaced_table[0]))]
                df = pd.DataFrame(spaced_table[1:], columns=headers).dropna(how="all")
                # Save
                df.to_csv(f"{output_folder}/table_page_{page_num}_spaced_{table_count}.csv", index=False)
                print(f"Saved spaced table {table_count} from page {page_num}")

    print(f"Total tables extracted: {table_count}")


if __name__ == "__main__":
    pdf_file_path = "Amazon-2024-Annual-Report.pdf"
    # Adjust min_gap based on PDF (larger = fewer columns, smaller = more columns)
    extract_tables_from_pdf(pdf_file_path, min_gap=5)
