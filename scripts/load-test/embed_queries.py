#!/usr/bin/env python3
"""
embed_queries.py — One-time utility to pre-embed a bank of domain-realistic queries
via Azure OpenAI. Output is written to query_bank.json as [{text, vector}] pairs.

Usage:
    python embed_queries.py

Environment variables required:
    AOAI_ENDPOINT               https://<name>.openai.azure.com
    AOAI_EMBEDDING_DEPLOYMENT   text-embedding-ada-002 (or your deployment name)
"""

import json
import os
import sys
from pathlib import Path

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

QUERIES = [
    # Surgical technique
    "recommended surgical technique for total knee replacement",
    "tibial component alignment in primary knee arthroplasty",
    "femoral component rotation in TKA",
    "surgical approach for unicompartmental knee replacement",
    "cemented vs cementless fixation in knee arthroplasty",
    # VELYS robotic system
    "VELYS robotic system setup and calibration procedure",
    "VELYS robotic assisted TKA workflow",
    "VELYS system registration and bone preparation steps",
    "VELYS intraoperative gap balancing technique",
    "VELYS system troubleshooting and error codes",
    # Implant sizing and selection
    "knee implant sizing guide for primary TKA",
    "patella sizing and preparation in total knee replacement",
    "sports medicine implant sizing for active patients",
    "tibial insert thickness selection criteria",
    "how to select the correct femoral component size",
    # Contraindications and patient selection
    "knee arthroplasty contraindications and risk factors",
    "BMI thresholds for total knee replacement candidacy",
    "age considerations for unicompartmental knee replacement",
    "infection screening prior to joint arthroplasty",
    "neuromuscular conditions contraindicating knee replacement",
    # Post-operative care and rehabilitation
    "post-operative rehabilitation protocol after TKA",
    "weight bearing restrictions after knee arthroplasty",
    "deep vein thrombosis prophylaxis after joint replacement",
    "wound care and infection prevention after knee surgery",
    "expected range of motion milestones after TKA",
    # Sterilization and instrument handling
    "instrument sterilization requirements for surgical instruments",
    "autoclave cycle parameters for orthopedic instruments",
    "single-use instrument disposal guidelines",
    "pre-operative instrument tray assembly checklist",
    "cleaning and decontamination protocol for reusable instruments",
    # Complications and revision surgery
    "periprosthetic joint infection diagnosis and treatment",
    "aseptic loosening of tibial component management",
    "knee replacement stiffness and manipulation under anesthesia",
    "periprosthetic fracture classification and fixation",
    "revision total knee arthroplasty indications and planning",
    # Implant materials and design
    "polyethylene wear and oxidation in knee implants",
    "cobalt chromium alloy properties for orthopedic implants",
    "tibial baseplate fixation options cemented vs press-fit",
    "posterior stabilized vs cruciate retaining knee design",
    "rotating platform vs fixed bearing tibial insert",
    # Navigation and digital tools
    "computer assisted navigation in total knee arthroplasty",
    "patient specific instrumentation for TKA planning",
    "digital templating for knee replacement sizing",
    "intraoperative sensor technology for gap balancing",
    "augmented reality in orthopedic surgery workflow",
    # Clinical outcomes and registry data
    "fifteen year survivorship data for primary TKA",
    "patient reported outcomes after knee arthroplasty",
    "Oxford Knee Score interpretation after joint replacement",
    "KOOS functional outcomes total knee replacement",
    "national joint registry data implant performance comparison",
    # Anesthesia and pain management
    "regional anesthesia protocols for knee replacement",
    "multimodal pain management after total knee arthroplasty",
    "adductor canal block technique for knee surgery",
    "perioperative opioid reduction protocol joint replacement",
    "tranexamic acid dosing to reduce blood loss in TKA",
]

OUTPUT_FILE = Path(__file__).parent / "query_bank.json"


def get_client() -> AzureOpenAI:
    endpoint = os.environ.get("AOAI_ENDPOINT")
    if not endpoint:
        sys.exit("ERROR: AOAI_ENDPOINT environment variable is not set.")

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version="2024-02-01",
    )


def embed_queries(client: AzureOpenAI, deployment: str) -> list[dict]:
    print(f"Embedding {len(QUERIES)} queries using deployment '{deployment}' ...")
    results = []
    for i, text in enumerate(QUERIES, start=1):
        response = client.embeddings.create(input=text, model=deployment)
        vector = response.data[0].embedding
        results.append({"text": text, "vector": vector})
        print(f"  [{i:02d}/{len(QUERIES)}] {text[:60]}")
    return results


def main() -> None:
    deployment = os.environ.get("AOAI_EMBEDDING_DEPLOYMENT")
    if not deployment:
        sys.exit("ERROR: AOAI_EMBEDDING_DEPLOYMENT environment variable is not set.")

    client = get_client()
    bank = embed_queries(client, deployment)

    OUTPUT_FILE.write_text(json.dumps(bank, indent=2), encoding="utf-8")
    print(f"\nWrote {len(bank)} entries to {OUTPUT_FILE}")
    print("Each entry has 'text' (str) and 'vector' (list of 1536 floats).")


if __name__ == "__main__":
    main()
