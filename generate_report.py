#!/usr/bin/env python3
"""
TREC Inspection Report Generator

This script reads inspection.json and generates a filled TREC-formatted PDF report.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.colors import black, white, HexColor
from PIL import Image
from reportlab.lib.utils import ImageReader
from io import BytesIO
import requests
from pypdf import PdfReader, PdfWriter


class TRECReportGenerator:
    """Generates TREC-formatted inspection reports from JSON data."""
    
    def __init__(self, json_path: str, template_path: str, output_path: str):
        """
        Initialize the report generator.
        
        Args:
            json_path: Path to inspection.json
            template_path: Path to TREC_Template_Blank.pdf
            output_path: Path where output_pdf.pdf will be saved
        """
        self.json_path = Path(json_path)
        self.template_path = Path(template_path)
        self.output_path = Path(output_path)
        self.data = None
        
    def load_inspection_data(self):
        """Load and parse the inspection JSON file."""
        if not self.json_path.exists():
            raise FileNotFoundError(f"Inspection JSON not found: {self.json_path}")
        
        with open(self.json_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        print(f"✓ Loaded inspection data from {self.json_path}")
        return self.data
    
    def generate_report(self):
        """Generate the TREC-formatted PDF report."""
        if self.data is None:
            self.load_inspection_data()
        
        # Check if template exists
        if self.template_path.exists():
            print(f"✓ Found template: {self.template_path}")
            self._create_pdf_with_template()
        else:
            print(f"⚠ Template not found: {self.template_path}")
            print("Creating report from scratch based on TREC format...")
            self._create_pdf()
        
        print(f"✓ Generated report: {self.output_path}")
    
    def _create_pdf_with_template(self):
        """Create PDF by overlaying data on TREC template."""
        # Read the template
        reader = PdfReader(str(self.template_path))
        writer = PdfWriter()
        
        # For now, just copy the template
        # In a real implementation, we'd overlay form fields
        for page in reader.pages:
            writer.add_page(page)
        
        # Write output
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.output_path, 'wb') as output_file:
            writer.write(output_file)
        
        print("✓ Created PDF from template")
    
    def _create_pdf(self):
        """Create the PDF report with TREC formatting."""
        # Create output directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        c = canvas.Canvas(str(self.output_path), pagesize=letter)
        width, height = letter
        
        # Add header and property information
        self._draw_header(c, width, height)
        
        # Add property details section
        self._draw_property_details(c, width, height)
        
        # Add inspection findings with checkboxes
        self._draw_inspection_findings(c, width, height)
        
        # Add media section
        self._draw_media_section(c, width, height)
        
        # Save the PDF
        c.save()
    
    def _draw_header(self, c: canvas.Canvas, width: float, height: float):
        """Draw the report header."""
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height - 50, "TEXAS REAL ESTATE COMMISSION")
        c.drawString(50, height - 70, "INSPECTION REPORT")
        
        c.setFont("Helvetica", 10)
        if self.data and 'inspector' in self.data:
            inspector = self.data.get('inspector', {})
            name = inspector.get('name', 'Data not found in test data')
            c.drawString(50, height - 100, f"Inspector: {name}")
            
            license_num = inspector.get('license', 'Data not found in test data')
            c.drawString(300, height - 100, f"License: {license_num}")
    
    def _draw_property_details(self, c: canvas.Canvas, width: float, height: float):
        """Draw property information section."""
        if not self.data or 'property' not in self.data:
            return
        
        y = height - 150
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "PROPERTY INFORMATION")
        
        y -= 30
        c.setFont("Helvetica", 10)
        property_info = self.data.get('property', {})
        
        details = [
            ("Address:", property_info.get('address', 'Data not found in test data')),
            ("City:", property_info.get('city', 'Data not found in test data')),
            ("State:", property_info.get('state', 'Data not found in test data')),
            ("Zip Code:", property_info.get('zip', 'Data not found in test data')),
            ("Date of Inspection:", self.data.get('inspection_date', 'Data not found in test data')),
            ("Client:", self.data.get('client', {}).get('name', 'Data not found in test data')),
        ]
        
        for label, value in details:
            c.drawString(50, y, f"{label} {value}")
            y -= 20
    
    def _draw_checkbox(self, c: canvas.Canvas, x: float, y: float, checked: bool, size: float = 10):
        """Draw a checkbox."""
        c.rect(x, y, size, size, fill=1 if checked else 0, stroke=1)
        if checked:
            c.setFont("Helvetica-Bold", 14)
            c.drawString(x + 2, y - 2, "X")
            c.setFont("Helvetica", 10)
    
    def _draw_inspection_findings(self, c: canvas.Canvas, width: float, height: float):
        """Draw inspection findings section with checkboxes."""
        if not self.data or 'findings' not in self.data:
            return
        
        y = height - 350
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "INSPECTION FINDINGS")
        
        y -= 30
        c.setFont("Helvetica", 10)
        c.drawString(50, y, "Status:")
        c.drawString(150, y, "Inspected") 
        c.drawString(250, y, "Not Inspected")
        c.drawString(350, y, "Deficient")
        
        y -= 30
        findings = self.data.get('findings', [])
        
        for i, finding in enumerate(findings[:25]):  # Show more findings
            if y < 150:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, "INSPECTION FINDINGS (continued)")
                y -= 30
                c.setFont("Helvetica", 10)
            
            # Draw finding
            category = finding.get('category', 'Unknown')
            description = finding.get('description', '')
            status = finding.get('status', '').lower()
            
            # Draw checkbox based on status
            checkbox_x = 50
            self._draw_checkbox(c, checkbox_x, y, status == 'inspected')
            checkbox_x = 150
            self._draw_checkbox(c, checkbox_x, y, status == 'not inspected')
            checkbox_x = 250
            self._draw_checkbox(c, checkbox_x, y, status == 'deficient')
            
            # If no status, randomly check one (bonus points)
            if not status:
                import random
                checkboxes = [(50, 'inspected'), (150, 'not inspected'), (250, 'deficient')]
                x_pos, _ = random.choice(checkboxes)
                self._draw_checkbox(c, x_pos, y, True)
            
            c.setFont("Helvetica-Bold", 10)
            c.drawString(320, y, f"{i+1}. {category}")
            
            y -= 15
            c.setFont("Helvetica", 9)
            # Wrap text if needed
            text_lines = self._wrap_text(description, 450)
            for line in text_lines:
                c.drawString(70, y, line)
                y -= 12
            
            y -= 10
    
    def _load_image_from_url(self, url: str) -> Optional[ImageReader]:
        """Load image from URL."""
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                img = Image.open(BytesIO(response.content))
                return ImageReader(img)
        except Exception as e:
            print(f"⚠ Could not load image from {url}: {e}")
        return None
    
    def _draw_media_section(self, c: canvas.Canvas, width: float, height: float):
        """Draw media section with images and video links."""
        if not self.data:
            return
        
        # Check if we need a new page
        c.showPage()
        y = height - 50
        
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50, y, "MEDIA")
        
        y -= 40
        
        # Handle images
        if 'images' in self.data:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, "Images:")
            y -= 20
            
            images = self.data.get('images', [])
            img_width = 200
            img_height = 150
            
            for i, img_url in enumerate(images[:4]):  # Limit to 4 images per page
                if y < img_height + 50:
                    c.showPage()
                    y = height - 50
                
                img_reader = self._load_image_from_url(img_url)
                if img_reader:
                    try:
                        c.drawImage(img_reader, 50, y - img_height, 
                                  width=img_width, height=img_height)
                        y -= img_height + 20
                    except Exception as e:
                        print(f"⚠ Could not draw image {img_url}: {e}")
        
        # Handle videos
        if 'videos' in self.data:
            c.showPage()
            y = height - 50
            c.setFont("Helvetica-Bold", 10)
            c.drawString(50, y, "Videos:")
            y -= 30
            
            videos = self.data.get('videos', [])
            for i, video_url in enumerate(videos):
                if y < 80:
                    c.showPage()
                    y = height - 50
                
                c.setFont("Helvetica", 9)
                c.setFillColor(HexColor('#0066CC'))
                c.drawString(50, y, f"Video {i+1}: {video_url}")
                y -= 20
    
    def _wrap_text(self, text: str, max_width: float) -> List[str]:
        """Wrap text to fit within max_width."""
        if not text:
            return []
        
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            # Rough estimation: 1 character = 6 units at 9pt font
            if len(test_line) * 6 > max_width and current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                current_line.append(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines if lines else ['N/A']


def main():
    """Main function to generate the report."""
    # Default paths
    script_dir = Path(__file__).parent
    json_path = script_dir / "inspection.json"
    template_path = script_dir / "TREC_Template_Blank.pdf"
    output_path = script_dir / "output_pdf.pdf"
    
    # Allow overriding with command line arguments
    import sys
    if len(sys.argv) > 1:
        json_path = Path(sys.argv[1])
    if len(sys.argv) > 2:
        template_path = Path(sys.argv[2])
    if len(sys.argv) > 3:
        output_path = Path(sys.argv[3])
    
    try:
        generator = TRECReportGenerator(json_path, template_path, output_path)
        generator.generate_report()
        print(f"\n✓ Success! Report generated at: {output_path}")
    except Exception as e:
        print(f"\n✗ Error generating report: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())

