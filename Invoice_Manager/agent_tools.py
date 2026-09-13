import logging
import os
import re
from PyPDF2 import PdfReader, PdfWriter
import PyPDF2
from typing import List, Dict, Any
import json
import pdf2image
import pytesseract
import fitz
import pandas as pd
import extract_msg
from azure.storage.blob import BlobServiceClient
from openai import AzureOpenAI
from helper_functions.pdf_proccessing_helpers import PDF_Document
from models.models import ContractClauseList
from utility.utility import (
    convert_pdf_to_images_base64,
    get_responseJSON,
    get_azureClient,
)

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get configuration from environment variables
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")


# Initialize Azure OpenAI client
client = get_azureClient()


# Define output columns for structured data
output_columns = [
    "invoiceNumber",
    "invoiceDate",
    "deliveryDate",
    "inItem",
    "poItem",
    "qtyInItem",
    "qtyPoItem",
    "qtyDiscrepancy",
    "unitPriceInItem",
    "unitPricePoItem",
    "unitPriceDiscrepancy",
    "totalInItem",
    "totalPoItem",
    "discrepancySummary",
    "poNumber",
]


# process single page PDF file
def process_single_pdf(
    client: AzureOpenAI,
    pdf_path: str,
    origin_path: str,
) -> PDF_Document:
    """
    Process a single PDF file and return a Document object.
    If successful and blob args are provided, upload the PDF into
    processed_prefix in blob storage and delete the original blob.
    On failure, leave the blob in place and log an error.
    """
    try:
        # run your AI/document logic
        d = PDF_Document(pdf_path, origin_path, client)
        return d

    except Exception as e:
        logger.error(f"Error processing PDF '{pdf_path}': {e}", exc_info=True)
        return None


# good receipt note tool
def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing or replacing problematic characters.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename safe for file operations
    """
    # Replace problematic characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*#]', "_", filename)
    # Remove multiple consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove leading/trailing underscores and spaces
    sanitized = sanitized.strip("_ ")
    sanitized = sanitized.replace(" ", "_")

    return sanitized


# detect and correct pdf orientation
def detect_and_correct_pdf_orientation(pdf_path: str, output_path: str = None) -> str:
    """
    Detect and correct PDF page orientation for better text extraction.

    Args:
        pdf_path: Path to the input PDF
        output_path: Path to save corrected PDF (optional)

    Returns:
        Path to the corrected PDF
    """
    if output_path is None:
        output_path = pdf_path.replace(".pdf", "_corrected.pdf")

    try:
        with open(pdf_path, "rb") as pdf_file:
            reader = PdfReader(pdf_file)
            writer = PdfWriter()

            for page_num, page in enumerate(reader.pages):
                # Convert page to image for orientation detection
                temp_pdf = PdfWriter()
                temp_pdf.add_page(page)

                temp_path = f"/tmp/temp_page_{page_num}.pdf"
                with open(temp_path, "wb") as temp_file:
                    temp_pdf.write(temp_file)

                # Convert to image and detect orientation
                images = pdf2image.convert_from_path(temp_path, dpi=300)

                if images:
                    img = images[0]

                    osd_data = pytesseract.image_to_osd(
                        img, output_type=pytesseract.Output.DICT
                    )
                    rotation = osd_data.get("orientation")

                    if rotation != 0:
                        # Test different rotations and find the best one
                        best_rotation = 0
                        best_confidence = 0

                        for rotation in [0, 90, 180, 270]:
                            rotated_img = img.rotate(rotation, expand=True)

                            # Use Tesseract to get OCR confidence
                            try:
                                ocr_data = pytesseract.image_to_data(
                                    rotated_img, output_type=pytesseract.Output.DICT
                                )
                                confidences = [
                                    int(conf)
                                    for conf in ocr_data["conf"]
                                    if int(conf) > 0
                                ]
                                avg_confidence = (
                                    sum(confidences) / len(confidences)
                                    if confidences
                                    else 0
                                )

                                if avg_confidence > best_confidence:
                                    best_confidence = avg_confidence
                                    best_rotation = rotation
                            except Exception as e:
                                logger.warning(
                                    f"OCR failed for rotation {rotation}: {e}"
                                )

                        logger.info(
                            f"Page {page_num}: Best rotation = {best_rotation}° (confidence: {best_confidence:.2f})"
                        )

                        # Apply the best rotation to the PDF page
                        if best_rotation != 0:
                            page.rotate(
                                -best_rotation
                            )  # Negative because PDF rotation is opposite

                writer.add_page(page)

                # Clean up temp file
                if os.path.exists(temp_path):
                    os.remove(temp_path)

            # Write corrected PDF
            with open(output_path, "wb") as output_file:
                writer.write(output_file)

            logger.info(f"Corrected PDF saved to: {output_path}")
            return output_path

    except Exception as e:
        logger.error(f"Error correcting PDF orientation: {e}")
        return pdf_path  # Return original if correction fails


# read pdf from .msg file (email)
def goods_receipt_note_tool() -> str:
    """
    Read and extract content from an Outlook .msg file including PDF attachments.

    Args:
        source_path (str): Path to the .msg file or blob path
        from_blob (bool): If True, source_path is treated as a blob path

    Returns:
        str: Extracted content from the goods receipt note PDF attachment or error message
    """

    msg_file_path = "/workspace/contract_document/singapore_grn.msg"
    # file_path = "/workspace/contract_document/Master_Service_Contract_01Aug17.pdf"
    save_directory = "/workspace/contract_document/processed/"

    grn_data = ""

    # Create the save directory if it doesn't exist
    os.makedirs(save_directory, exist_ok=True)

    msg = extract_msg.Message(msg_file_path)

    for attachment in msg.attachments:
        att_info = {
            "name": attachment.longFilename,
            "type": (
                attachment.longFilename.split(".")[-1].lower()
                if "." in attachment.longFilename
                else "unknown"
            ),
        }

        # Handle PDF attachments
        if att_info["type"] == "pdf":
            # Sanitize the attachment filename to avoid issues with special characters
            attachment_filename = sanitize_filename(attachment.longFilename)
            temp_pdf_path = os.path.join(save_directory, attachment_filename)

            # Write attachment data to file
            with open(temp_pdf_path, "wb") as f:
                f.write(attachment.data)

            logger.info(f"PDF downloaded to: {temp_pdf_path}")

            try:
                # Detect and correct PDF orientation
                corrected_pdf_path = detect_and_correct_pdf_orientation(
                    temp_pdf_path,
                    os.path.join(save_directory, f"corrected_{attachment_filename}"),
                )

                # Convert corrected PDF pages to images and extract text and Higher DPI for better OCR
                images = pdf2image.convert_from_path(corrected_pdf_path, dpi=300)

                # Iterate over each image and perform OCR
                for i, image in enumerate(images):
                    # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
                    image_gray = image.convert("L")
                    # Extract text using Tesseract with safer configuration
                    try:
                        # Use a simpler, more robust Tesseract configuration
                        custom_config = r"--oem 3 --psm 6"
                        text = pytesseract.image_to_string(
                            image_gray, config=custom_config
                        )
                    except Exception as ocr_error:
                        logger.warning(
                            f"OCR with custom config failed: {ocr_error}, trying default"
                        )
                        # Fallback to default OCR settings
                        text = pytesseract.image_to_string(image_gray)

                    # Ensure text is not None and is a string
                    if text is None:
                        text = ""
                    text = str(text).strip()

                    grn_data += f"--- Page {i+1} ---\n{text.strip()}\n\n"

                logger.info(f"Successfully extracted text from {len(images)} pages")
                # Clean up temp file
                os.remove(temp_pdf_path)
                os.remove(corrected_pdf_path)
                return grn_data.strip()
            except Exception as e:
                logger.error(f"Error processing {temp_pdf_path}: {e}")
                # Fallback: try without orientation correction
                try:
                    logger.info(
                        "Attempting fallback processing without orientation correction"
                    )
                    images = pdf2image.convert_from_path(corrected_pdf_path, dpi=300)

                    for i, image in enumerate(images):
                        # Simple OCR without special configuration
                        text = pytesseract.image_to_string(image)
                        # Ensure text is not None and is a string
                        if text is None:
                            text = ""
                        text = str(text).strip()
                        grn_data += f"--- Page {i+1} (fallback) ---\n{text}\n"
                    os.remove(temp_pdf_path)
                    os.remove(corrected_pdf_path)
                    return grn_data
                except Exception as fallback_error:
                    logger.error(f"Fallback processing also failed: {fallback_error}")
                    return f"Error processing PDF: {str(e)}"
        else:
            logger.info(f"Skipping non-PDF attachment: {att_info['name']}")

    msg.close()
    # If no PDF attachments were found, return appropriate message
    return "No PDF attachments found in the message file"


# goods receipt note tool read pdf using pytesseract
def goods_receipt_note_pdf_tool() -> str:
    """
    Fetch goods receipt note content from Azure Blob Storage.

    Returns:
        str: Goods receipt note content or error message
    """

    # grn_file_name = "sample_goods_receipt_note.pdf"
    grn_file_name = "goods_receipt_note_anton_paar.pdf"
    grn_file_path = f"/workspace/contract_document/{grn_file_name}"

    grn_content = ""

    # extracting content from PDF, including xerox scanned pdf with pytesseract
    try:
        # Convert corrected PDF pages to images and extract text and Higher DPI for better OCR
        images = pdf2image.convert_from_path(grn_file_path, dpi=300)

        # Iterate over each image and perform OCR
        for i, image in enumerate(images):
            # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
            image_gray = image.convert("L")
            # Extract text using Tesseract with safer configuration
            try:
                # Use a simpler, more robust Tesseract configuration
                custom_config = r"--oem 3 --psm 6"
                text = pytesseract.image_to_string(image_gray, config=custom_config)
            except Exception as ocr_error:
                logger.warning(
                    f"OCR with custom config failed: {ocr_error}, trying default"
                )
                # Fallback to default OCR settings
                text = pytesseract.image_to_string(image_gray)

            # Ensure text is not None and is a string
            if text is None:
                text = ""
            text = str(text).strip()

            grn_content += f"--- Page {i+1} ---\n{text.strip()}\n\n"

        logger.info(
            f"Successfully extracted text from goods receipt note - {len(images)} pages"
        )
    except Exception as e:
        print(f"Error processing {grn_file_path}: {e}")

    return grn_content


# invoice extraction tool read pdf from msg file
def invoice_parser_tool() -> str:
    """
    Extract text content from a PDF file.

    Args:
        src_path (str): Path to the PDF file

    Returns:
        str: Extracted text content from the PDF
    """

    msg_file_name = ""
    # msg_file_name = "EXTERNAL_Invoice_from_Insight_Direct_USA_Inc.msg"
    msg_file_name = "EXTERNAL_CHEVRON_4262511.msg"

    msg_file_path = f"/workspace/contract_document/{msg_file_name}"

    save_directory = "/workspace/contract_document/processed/"

    invoice_data = ""

    # Create the save directory if it doesn't exist
    os.makedirs(save_directory, exist_ok=True)

    msg = extract_msg.Message(msg_file_path)
    # extracting content from PDF, including xerox copy as images
    for attachment in msg.attachments:
        att_info = {
            "name": attachment.longFilename,
            "type": (
                attachment.longFilename.split(".")[-1].lower()
                if "." in attachment.longFilename
                else "unknown"
            ),
        }

        # Handle PDF attachments
        if att_info["type"] == "pdf":
            # Sanitize the attachment filename to avoid issues with special characters
            attachment_filename = sanitize_filename(attachment.longFilename)
            temp_pdf_path = os.path.join(save_directory, attachment_filename)

            # Write attachment data to file
            with open(temp_pdf_path, "wb") as f:
                f.write(attachment.data)

            logger.info(f"PDF downloaded to: {temp_pdf_path}")

            try:
                # Detect and correct PDF orientation
                corrected_pdf_path = detect_and_correct_pdf_orientation(
                    temp_pdf_path,
                    os.path.join(save_directory, f"corrected_{attachment_filename}"),
                )

                # Convert corrected PDF pages to images and extract text and Higher DPI for better OCR
                images = pdf2image.convert_from_path(corrected_pdf_path, dpi=300)

                # Iterate over each image and perform OCR
                for i, image in enumerate(images):
                    # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
                    image_gray = image.convert("L")
                    # Extract text using Tesseract with safer configuration
                    try:
                        # Use a simpler, more robust Tesseract configuration
                        custom_config = r"--oem 3 --psm 6"
                        text = pytesseract.image_to_string(
                            image_gray, config=custom_config
                        )
                    except Exception as ocr_error:
                        logger.warning(
                            f"OCR with custom config failed: {ocr_error}, trying default"
                        )
                        # Fallback to default OCR settings
                        text = pytesseract.image_to_string(image_gray)

                    # Ensure text is not None and is a string
                    if text is None:
                        text = ""
                    text = str(text).strip()

                    invoice_data += f"--- Page {i+1} ---\n{text.strip()}\n\n"

                logger.info(f"Successfully extracted text from {len(images)} pages")
                # Clean up temp file
                os.remove(temp_pdf_path)
                os.remove(corrected_pdf_path)
                return invoice_data.strip()
            except Exception as e:
                logger.error(f"Error processing {temp_pdf_path}: {e}")
                # Fallback: try without orientation correction
                try:
                    logger.info(
                        "Attempting fallback processing without orientation correction"
                    )
                    images = pdf2image.convert_from_path(temp_pdf_path, dpi=300)

                    for i, image in enumerate(images):
                        # Simple OCR without special configuration
                        text = pytesseract.image_to_string(image)
                        # Ensure text is not None and is a string
                        if text is None:
                            text = ""
                        text = str(text).strip()
                        invoice_data += f"--- Page {i+1} (fallback) ---\n{text}\n"
                    os.remove(temp_pdf_path)
                    os.remove(corrected_pdf_path)
                    return invoice_data
                except Exception as fallback_error:
                    logger.error(f"Fallback processing also failed: {fallback_error}")
                    return f"Error processing PDF: {str(e)}"
        else:
            logger.info(f"Skipping non-PDF attachment: {att_info['name']}")

    msg.close()
    # If no PDF attachments were found, return appropriate message
    return "No PDF attachments found in the message file"


# purchase order tool read pdf directly
def invoice_parser_pdf_tool() -> str:
    """
    Fetch invoice content from Azure Blob Storage.

    Returns:
        str: Invoice content or error message
    """

    invoice_file_name = "Invoice_anton_paar_890239714_61218996.pdf"
    invoice_file_path = f"/workspace/contract_document/{invoice_file_name}"
    invoice_content = ""

    # extracting content from PDF, including xerox scanned pdf with pytesseract
    try:
        # Convert PDF pages to a list of images
        images = pdf2image.convert_from_path(invoice_file_path, dpi=300)

        # Iterate over each image and perform OCR
        for i, image in enumerate(images):
            # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
            image_gray = image.convert("L")
            # Extract text using Tesseract with safer configuration
            try:
                # Use a simpler, more robust Tesseract configuration
                custom_config = r"--oem 3 --psm 6"
                text = pytesseract.image_to_string(image_gray, config=custom_config)
            except Exception as ocr_error:
                logger.warning(
                    f"OCR with custom config failed: {ocr_error}, trying default"
                )
                # Fallback to default OCR settings
                text = pytesseract.image_to_string(image_gray)

            # Ensure text is not None and is a string
            if text is None:
                text = ""
            text = str(text).strip()

            invoice_content += f"--- Page {i+1} ---\n{text.strip()}\n\n"

        logger.info(f"Successfully extracted text from invoice - {len(images)} pages")

        # Iterate over each image and perform OCR
        # for i, image in enumerate(images):
        #     text = pytesseract.image_to_string(image)
        #     invoice_content += f"--- Page {i+1} ---\n{text}\n"
    except Exception as e:
        print(f"Error processing {invoice_file_path}: {e}")

    return invoice_content


# purchase order tool read pdf directly
def purchase_order_tool():
    """
    Fetch purchase order content from excel file.

    Returns:
        str: Purchase order content or error message
    """
    # po_file_name = "sample_purchase_order.pdf"
    po_file_name = "Order_report_for_GR_RPA.xlsx"
    po_file_path = f"/workspace/contract_document/{po_file_name}"
    df = pd.DataFrame()

    try:
        df = pd.read_excel(
            po_file_path,
            engine="openpyxl",
            usecols=["Order Number", "Description", "Unit Price"],
        )
        logger.info(f"Successfully read purchase order Excel file: {po_file_name}")
        # pd.set_option("display.max_rows", 40)
        # print(df)
    except Exception as e:
        logger.error(f"Error reading Excel file {po_file_name}: {e}")

    return df


# contract extraction tool read pdf directly
def contract_parser_tool() -> str:
    """
    Fetch contract content from a folder.

    Returns:
        str: Contract content or error message
    """

    contract_file_name = "Contract-C1874986-Executed.pdf"
    # contract_file_name = "sample_contract_term.pdf"
    # contract_file_name = "Contract-C1874986-Executed.pdf"

    file_path = f"/workspace/contract_document/{contract_file_name}"

    contract_content = ""

    # extracting content from PDF, including xerox scanned pdf with base64
    # try:
    #     with open(file_path, "rb") as pdf_file:
    #         encoded_string = base64.b64encode(pdf_file.read())
    #     return encoded_string
    # except FileNotFoundError:
    #     print(f"Error: The file '{file_path}' was not found.")
    #     return None
    # except Exception as e:
    #     print(f"An error occurred: {e}")
    #     return None

    # Convert corrected PDF pages to images and extract text and Higher DPI for better OCR
    try:
        images = pdf2image.convert_from_path(file_path, dpi=150)
    except Exception as e:
        print(f"Error processing {file_path}: {e}")

    # Iterate over each image and perform OCR
    for i, image in enumerate(images):
        # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
        image_gray = image.convert("L")
        # Extract text using Tesseract with safer configuration
        try:
            # Use a simpler, more robust Tesseract configuration
            custom_config = r"--oem 3 --psm 6"
            text = pytesseract.image_to_string(image_gray, config=custom_config)
        except Exception as ocr_error:
            logger.warning(
                f"OCR with custom config failed: {ocr_error}, trying default"
            )
            # Fallback to default OCR settings
            text = pytesseract.image_to_string(image_gray)

        # Ensure text is not None and is a string
        if text is None:
            text = ""
        text = str(text).strip()

        contract_content += f"--- Page {i+1} ---\n{text.strip()}\n\n"

    logger.info(f"Successfully extracted text from {len(images)} pages")

    messages = []
    messages.append({"role": "user", "content": f"Contract text:\n{contract_content}"})

    completion = get_responseJSON(
        get_azureClient(),
        messages,
        ContractSummary,
        deployment_name="gpt-5-mini",
    )

    raw_content = completion.choices[0].message.content
    contract_dict = json.loads(raw_content)

    # doc = fitz.open(file_path)
    # for page in doc:
    #     contract_content += page.get_text()
    # doc.close()

    # if len(contract_content.strip()) == 0:
    #     # Convert corrected PDF pages to images and extract text and Higher DPI for better OCR
    #     try:
    #         images = pdf2image.convert_from_path(file_path, dpi=150)
    #     except Exception as e:
    #         print(f"Error processing {file_path}: {e}")

    #     # Iterate over each image and perform OCR
    #     for i, image in enumerate(images):
    #         # Apply image preprocessing for better OCR and Convert to grayscale and enhance contrast
    #         image_gray = image.convert("L")
    #         # Extract text using Tesseract with safer configuration
    #         try:
    #             # Use a simpler, more robust Tesseract configuration
    #             custom_config = r"--oem 3 --psm 6"
    #             text = pytesseract.image_to_string(image_gray, config=custom_config)
    #         except Exception as ocr_error:
    #             logger.warning(
    #                 f"OCR with custom config failed: {ocr_error}, trying default"
    #             )
    #             # Fallback to default OCR settings
    #             text = pytesseract.image_to_string(image_gray)

    #         # Ensure text is not None and is a string
    #         if text is None:
    #             text = ""
    #         text = str(text).strip()

    #         contract_content += f"--- Page {i+1} ---\n{text.strip()}\n\n"

    #     logger.info(f"Successfully extracted text from {len(images)} pages")

    # return  contract_content.strip()
    return contract_dict


# read email message from blob container and extract the pdf content from the attachment
def read_msg_file() -> str:
    """
    Read and extract content from an Outlook .msg file including PDF attachments.

    Args:
        source_path (str): Path to the .msg file or blob path
        from_blob (bool): If True, source_path is treated as a blob path

    Returns:
        Dict[str, Any]: Dictionary containing extracted message contents with keys:
            - subject: Email subject
            - sender: Sender's email
            - date: Send date
            - body: Email body text
            - attachments: List of dictionaries containing:
                - name: Attachment filename
                - content: Text content (if PDF)
                - type: File type
            - raw_text: Complete raw text including headers
    """
    try:
        # Get blob content
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            connection_string = ""
            logger.warning(
                "Using hardcoded connection string. Set AZURE_STORAGE_CONNECTION_STRING environment variable."
            )

        blob_service_client = BlobServiceClient.from_connection_string(
            connection_string
        )
        container_name = os.getenv(
            "CONTRACT_CONTAINER_NAME", "mssc-contract-intelligence"
        )
        blob_name = os.getenv(
            "CONTRACT_BLOB_NAME",
            "goods_receipt_note/singapore_grn.msg",
        )

        # Get blob client and download to memory
        blob_client = blob_service_client.get_blob_client(
            container=container_name, blob=blob_name
        )
        msg_content = blob_client.download_blob()

        # Save to temporary file
        temp_path = "/tmp/temp.msg"
        with open(temp_path, "wb") as temp_file:
            msg_content.readinto(temp_file)

        msg = extract_msg.Message(temp_path)
        os.remove(temp_path)  # Clean up temp file

        # Process attachments
        attachments = []
        for attachment in msg.attachments:
            att_info = {
                "name": attachment.longFilename,
                "type": (
                    attachment.longFilename.split(".")[-1].lower()
                    if "." in attachment.longFilename
                    else "unknown"
                ),
            }

            # Handle PDF attachments
            if att_info["type"] == "pdf":
                try:
                    # Save attachment to temp file
                    temp_pdf_path = f"/tmp/{attachment.longFilename}"
                    with open(temp_pdf_path, "wb") as f:
                        f.write(attachment.data)

                    # Read PDF content
                    pdf_content = ""
                    with open(temp_pdf_path, "rb") as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        for page in pdf_reader.pages:
                            content = page.extract_text()
                            # Clean up content
                            content = content.replace("\r\n", " ").replace("\n", " ")
                            pdf_content += content + "\n\n"

                    att_info["content"] = pdf_content.strip()
                    os.remove(temp_pdf_path)  # Clean up
                except Exception as e:
                    logger.error(
                        f"Error processing PDF attachment {attachment.longFilename}: {str(e)}"
                    )
                    att_info["content"] = f"Error extracting PDF content: {str(e)}"
            else:
                att_info["content"] = None

            attachments.append(att_info)

        msg.close()
        return attachments

    except Exception as e:
        error_msg = f"Error reading .msg file: {str(e)}"
        logger.error(error_msg)
        return error_msg


# Contract parser tool that returns structured response
def contract_parser_tool_new() -> Dict[str, Any]:
    """
    Extract contract content and return structured data matching ContractResponseFormat schema.

    Returns:
        Dict[str, Any]: Dictionary with contract data structured according to ContractSummary
    """
    contract_dict = []

    try:
        # Get the contract content using the existing logic
        contract_file_name = "IAM-025-MRC.pdf"

        pdf_path = f"/workspace/contract_document/{contract_file_name}"
        contract_content = ""

        # Extract text from original PDF document using PyMuPDF
        doc = fitz.open(pdf_path)
        for page in doc:
            contract_content += page.get_text()
        doc.close()

        # check if the pdf is scanned or text-based, if no text found, convert PDF to images
        images_content = []
        messages = []

        if len(contract_content.strip()) == 0:
            # images_content = prepare_images_content(pdf_path)

            images = pdf2image.convert_from_path(pdf_path, dpi=300)

            for i, image in enumerate(images):
                # Simple OCR without special configuration
                text = pytesseract.image_to_string(image)
                # Ensure text is not None and is a string
                if text is None:
                    text = ""
                text = str(text).strip()
                contract_content += f"--- Page {i+1} (fallback) ---\n{text}\n"

            extract_prompt = get_extraction_prompt()
            messages.append(
                {
                    "role": "user",
                    "content": f"{extract_prompt} \n\nCONTRACT CONTENT:\n{contract_content}",
                }
            )

            # if not images_text:
            #     return f"Error: Unable to rasterize PDF {pdf_path}"
            # else:
            #     messages = [
            #         {
            #             "role": "system",
            #             "content": (
            #                 "Extract exactly one contract into the strict schema. "
            #                 "Extract exact words from the contract, do not paraphrase or summarize. "
            #             ),
            #         },
            #         {
            #             "role": "user",
            #             "content": [
            #                 {
            #                     "type": "text",
            #                     "text": get_extraction_prompt(),
            #                 },
            #                 *images_content,
            #             ],
            #         },
            #     ]
        else:
            messages.append(
                {"role": "user", "content": f"Contract text:\n{contract_content}"}
            )

        completion = get_responseJSON(
            get_azureClient(),
            messages,
            ContractClauseList,
            deployment_name="gpt-5-mini",
        )

        raw_content = completion.choices[0].message.content
        contract_dict = json.loads(raw_content)
    except Exception as e:
        logger.error(f"Error in contract_parser_tool_new: {e}")

    return contract_dict


# helper function to convert pdf to base64 images
def prepare_images_content(pdf_path: str) -> List[Dict]:
    try:
        images = convert_pdf_to_images_base64(pdf_path, dpi=200)
        logger.info(f"Extracted {len(images)} images from PDF '{pdf_path}'.")
        return [{"type": "image_url", "image_url": {"url": img}} for img in images]
    except Exception as e:
        logger.error(f"Error processing PDF '{pdf_path}': {e}")
        return []


def get_extraction_prompt() -> str:
    return """
    Analyze the CONTRACT CONTENT below then provide the output matching the ContractResponseFormat schema. 
    Extract exact words from the contract, do not paraphrase or summarize.
    
    For any field not found in the contract, use the value "Not specified in contract".
    Ensure all keys are present in your JSON response.
    """


def get_field_definition_prompt() -> str:
    return """
    Extract the relevant information from the contract text that refers to duties, roles, or responsibilities that differ from the primary job description outlined in this contract. 
    These functions may be assigned at the discretion of management based on business needs, employee capabilities, or organizational restructuring. 
    Such alternative functions may include, but are not limited to, tasks in different departments, project-based roles, 
    or temporary assignments that align with the employee's skills and experience. 
    Employees may be required to perform these functions in addition to or in lieu of their primary responsibilities, 
    ensuring flexibility and adaptability within the workforce. The assignment of alternative job functions shall be 
    communicated in writing, and any necessary training or resources will be provided to support the employee in fulfilling these additional duties.
    The assignment of alternative job functions shall be communicated in writing, and any necessary training 
    or resources will be provided to support the employee in fulfilling these additional duties.
    """
