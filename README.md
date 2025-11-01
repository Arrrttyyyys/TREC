# TREC Inspection Report Generator

A Python-based tool for generating Texas Real Estate Commission (TREC) formatted inspection reports from JSON data.

## Features

- ✅ **TREC Formatted Reports**: Generates PDF reports following official TREC format
- ✅ **Checkbox Handling**: Draws and fills checkboxes for inspection status (Inspected, Not Inspected, Deficient)
- ✅ **Image Embedding**: Loads and embeds images from URLs directly into PDF
- ✅ **Video Links**: Creates clickable video links that open in browser
- ✅ **Template Support**: Can overlay data on existing TREC template PDFs
- ✅ **Missing Data Handling**: Uses placeholder text for missing fields
- ✅ **Multi-page Support**: Automatically handles pagination for long reports
- ✅ **Professional Formatting**: Proper text wrapping and layout

## Installation

```bash
# Clone the repository
git clone https://github.com/Arrrttyyyys/TREC.git
cd TREC

# Install dependencies
pip install -r requirements.txt
```

## Requirements

- Python 3.8+
- pypdf>=3.0.0
- reportlab>=4.0.0
- Pillow>=10.0.0
- requests>=2.31.0

## Usage

### Basic Usage

```bash
python3 generate_report.py
```

This will:
- Look for `inspection.json` in the current directory
- Use `TREC_Template_Blank.pdf` as template (optional)
- Generate `output_pdf.pdf`

### Custom Paths

```bash
python3 generate_report.py inspection.json TREC_Template_Blank.pdf output_pdf.pdf
```

## JSON Input Format

The `inspection.json` file should have the following structure:

```json
{
  "inspector": {
    "name": "John Doe",
    "license": "12345"
  },
  "property": {
    "address": "123 Main St",
    "city": "Austin",
    "state": "TX",
    "zip": "78701"
  },
  "inspection_date": "2024-01-15",
  "client": {
    "name": "Jane Smith"
  },
  "findings": [
    {
      "category": "Foundation",
      "description": "Minor settling observed in northwest corner",
      "status": "Inspected"
    },
    {
      "category": "Electrical",
      "description": "All outlets functioning properly",
      "status": "Not Inspected"
    }
  ],
  "images": [
    "https://example.com/image1.jpg",
    "https://example.com/image2.jpg"
  ],
  "videos": [
    "https://example.com/video1.mp4"
  ]
}
```

## Status Values

For `findings.status`, use one of:
- `"Inspected"` - Item was inspected
- `"Not Inspected"` - Item was not inspected
- `"Deficient"` - Item has deficiencies
- Empty string or missing - Will randomly select a checkbox (bonus feature)

## Missing Data

If any data is missing, the generator will use the placeholder: **"Data not found in test data"**

## Template Mode

If `TREC_Template_Blank.pdf` exists, the script will attempt to use it as a template. Otherwise, it creates a report from scratch using the TREC format.

## Output

The generated PDF includes:
- TREC header with inspector information
- Property details section
- Inspection findings with visual checkboxes
- Embedded images with proper sizing
- Clickable video links
- Professional formatting with page breaks

## License

MIT License

## Contributing

Pull requests are welcome! For major changes, please open an issue first.

## Author

Arrrttyyyys

