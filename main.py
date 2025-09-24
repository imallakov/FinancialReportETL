import pdfplumber
import pandas as pd
import os
import re


def remove_internal_commas(text):
    """Remove commas from text while handling None values"""
    if text is None:
        return ""
    # Use regex to replace all commas with nothing
    return re.sub(r',', '', str(text))


def extract_tables_from_pdf(pdf_path, output_folder="extracted_tables"):
    """
    Extracts all tables from a PDF file, removes internal commas from content,
    and saves each table as a CSV file with comma-separated columns.

    Args:
        pdf_path (str): Path to the input PDF file
        output_folder (str): Folder to save extracted CSV files
    """
    # Create output folder if it doesn't exist
    os.makedirs(output_folder, exist_ok=True)

    # Open the PDF file
    with pdfplumber.open(pdf_path) as pdf:
        table_count = 0

        # Iterate through each page
        for page_num, page in enumerate(pdf.pages, start=1):
            print(f"Processing page {page_num}...")

            # Extract tables from the page with optimized settings
            tables = page.extract_tables(table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 5,
                "join_tolerance": 3,
                "edge_min_length": 3
            })

            # Process each table on the page
            for table in tables:
                if not table:  # Skip empty tables
                    continue

                table_count += 1

                # Remove commas from all cells in the table
                cleaned_table = []
                for row in table:
                    cleaned_row = [remove_internal_commas(cell) for cell in row]
                    cleaned_table.append(cleaned_row)

                # Create headers
                headers = cleaned_table[0] if any(cleaned_table[0]) else [f"Column_{i + 1}" for i in
                                                                          range(len(cleaned_table[0]))]

                # Create DataFrame with cleaned data
                df = pd.DataFrame(cleaned_table[1:], columns=headers)

                # Additional cleaning
                df = df.dropna(how="all")  # Remove empty rows
                df = df.replace(r'^\s*$', None, regex=True)  # Replace empty strings with None

                # Generate filename
                filename = f"table_page_{page_num}_table_{table_count}.csv"
                output_path = os.path.join(output_folder, filename)

                # Save to CSV with comma as separator (default)
                # Since we removed internal commas, this will work correctly
                df.to_csv(output_path, index=False)
                print(f"Saved table {table_count} from page {page_num} to {output_path}")

    print(f"Extraction complete. Total tables extracted: {table_count}")


if __name__ == "__main__":
    # Example usage
    pdf_file_path = "Amazon-2024-Annual-Report.pdf"  # Replace with your PDF path
    extract_tables_from_pdf(pdf_file_path)
