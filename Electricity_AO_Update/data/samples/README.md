# Public sample agreements

These Electricity Facts Label PDFs are included only as parser-development fixtures. They are historical disclosures, may be specific to one Texas TDU service area, and must not be treated as currently available offers.

- `txu.pdf`: official TXU sample EFL for Texas Choice. Its delivery charges are referenced externally, so the optimizer should flag incomplete pricing.
- `gexa.pdf`: Gexa Energy Saver 24 EFL dated May 16, 2025 for the CenterPoint service area.
- `constellation.pdf`: Constellation 12-month fixed-rate EFL dated June 26, 2025 for the CenterPoint service area. Its minimum-usage condition tests unsupported-fee review.

Source URLs and retrieval date (September 13, 2026):

- https://www.txu.com/-/media/Project/VistraApps/DT/Files/Content-Pages/Help-Center/Sample-EFL-English.pdf
- https://powerviewstorageprod.blob.core.windows.net/public-pdfs/Gexa_Energy_EFL9_20250610_072620_prodcode_GXA_ENRGSVR_24.pdf
- https://www.powerchoicetexas.org/index.php/ajax/base64_doc/1322/4847748/electricity-facts-label.pdf

To use them in the notebook, set `PROVIDERS_PATH = ROOT / "data/samples/providers.json"`, supply an API key, and use live mode. The documents will be sent to OpenAI as extracted text.
