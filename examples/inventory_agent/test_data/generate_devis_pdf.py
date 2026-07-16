"""
Generate sample PDF devis for testing.
Uses reportlab to create simple PDF documents.
"""


def create_simple_devis():
    """Create a simple text-based devis that can be read easily."""

    devis_content = """
DEVIS N° 2024-001
==================

Date: 15/07/2024
Client: Marie Martin
Société: InnoSoft
Email: marie.martin@example.com

DÉTAILS DE LA COMMANDE
-----------------------

Produit: Webcam HD
Quantité: 15
Prix unitaire: 79.99 €
Total: 1,199.85 €

Produit: Casque Audio Sony
Quantité: 10
Prix unitaire: 199.99 €
Total: 1,999.90 €

Produit: Hub USB-C
Quantité: 25
Prix unitaire: 49.99 €
Total: 1,249.75 €

TOTAL GÉNÉRAL: 4,449.50 €

Validité du devis: 30 jours
Délai de livraison: 5-7 jours ouvrés

---
Pour valider ce devis, merci de nous retourner ce document signé.
"""

    # Save as text file (simplest approach)
    with open("devis_2024_001.txt", "w", encoding="utf-8") as f:
        f.write(devis_content)

    print("✅ Devis text file created: devis_2024_001.txt")

    # Try to create PDF if reportlab is available
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import cm

        pdf_file = "devis_2024_001.pdf"
        c = canvas.Canvas(pdf_file, pagesize=A4)
        width, height = A4

        # Title
        c.setFont("Helvetica-Bold", 18)
        c.drawString(2*cm, height - 3*cm, "DEVIS N° 2024-001")

        # Header info
        c.setFont("Helvetica", 11)
        y = height - 5*cm
        c.drawString(2*cm, y, "Date: 15/07/2024")
        c.drawString(2*cm, y - 0.6*cm, "Client: Marie Martin")
        c.drawString(2*cm, y - 1.2*cm, "Société: InnoSoft")
        c.drawString(2*cm, y - 1.8*cm, "Email: marie.martin@example.com")

        # Products section
        y = height - 8*cm
        c.setFont("Helvetica-Bold", 13)
        c.drawString(2*cm, y, "DÉTAILS DE LA COMMANDE")
        c.line(2*cm, y - 0.2*cm, width - 2*cm, y - 0.2*cm)

        # Product 1
        y -= 1.5*cm
        c.setFont("Helvetica", 11)
        c.drawString(2*cm, y, "Produit: Webcam HD")
        c.drawString(2*cm, y - 0.5*cm, "Quantité: 15 | Prix unitaire: 79.99 € | Total: 1,199.85 €")

        # Product 2
        y -= 1.5*cm
        c.drawString(2*cm, y, "Produit: Casque Audio Sony")
        c.drawString(2*cm, y - 0.5*cm, "Quantité: 10 | Prix unitaire: 199.99 € | Total: 1,999.90 €")

        # Product 3
        y -= 1.5*cm
        c.drawString(2*cm, y, "Produit: Hub USB-C")
        c.drawString(2*cm, y - 0.5*cm, "Quantité: 25 | Prix unitaire: 49.99 € | Total: 1,249.75 €")

        # Total
        y -= 2*cm
        c.line(2*cm, y, width - 2*cm, y)
        y -= 0.8*cm
        c.setFont("Helvetica-Bold", 13)
        c.drawString(2*cm, y, "TOTAL GÉNÉRAL: 4,449.50 €")

        # Footer
        y -= 2*cm
        c.setFont("Helvetica", 10)
        c.drawString(2*cm, y, "Validité du devis: 30 jours")
        c.drawString(2*cm, y - 0.5*cm, "Délai de livraison: 5-7 jours ouvrés")

        c.save()
        print(f"✅ PDF created: {pdf_file}")

    except ImportError:
        print("⚠️  reportlab not installed, PDF not created (text file available)")
        print("   Install with: pip install reportlab")


def create_second_devis():
    """Create another devis for testing."""

    devis_content = """
DEVIS N° 2024-002
==================

Date: 15/07/2024
Client: Jean Dupont
Société: TechCorp
Email: jean.dupont@example.com

DÉTAILS DE LA COMMANDE
-----------------------

Produit: Laptop Dell XPS 15
Quantité: 3
Prix unitaire: 1500.00 €
Total: 4,500.00 €

Produit: Écran 27 pouces 4K
Quantité: 6
Prix unitaire: 450.00 €
Total: 2,700.00 €

TOTAL GÉNÉRAL: 7,200.00 €

Validité du devis: 30 jours
Délai de livraison: 5-7 jours ouvrés

---
Pour valider ce devis, merci de nous retourner ce document signé.
"""

    with open("devis_2024_002.txt", "w", encoding="utf-8") as f:
        f.write(devis_content)

    print("✅ Devis text file created: devis_2024_002.txt")


if __name__ == "__main__":
    print("📄 Generating sample devis files...")
    print("-" * 60)
    create_simple_devis()
    create_second_devis()
    print("-" * 60)
    print("✅ Done! Use these files to test the PDF reader tool.")
