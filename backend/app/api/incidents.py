from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.connectors.file_connector import FileConnector
from app.db.repositories import IncidentRepository
from app.models.incident import IncidentAnalysis
from app.services.analysis_service import analyze
from app.services.active_incident import active_incident
from app.services.llm_service import enrich_with_llm


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

repository = IncidentRepository()


@router.post("/analyze", response_model=IncidentAnalysis)
async def analyze_incident(
    files: list[UploadFile] = File(...)
) -> IncidentAnalysis:
    events = []
    file_errors = []

    for upload in files:
        try:
            connector = FileConnector(
                upload.filename or "unknown",
                await upload.read(),
            )
            events.extend(connector.collect())

        except ValueError as exc:
            file_errors.append(
                f"{upload.filename or 'unknown'}: {exc}"
            )

        except Exception as exc:
            file_errors.append(
                f"{upload.filename or 'unknown'}: "
                f"could not process file ({exc})"
            )

    return enrich_with_llm(analyze(events, file_errors))


@router.get("/active")
def get_active_incident() -> dict[str, object]:
    events = active_incident.snapshot()

    return {
        "events": events,
        "count": len(events),
    }


@router.get("")
def list_incidents() -> list[dict]:
    return repository.list_incidents()


@router.get("/{incident_id}")
def get_incident_detail(incident_id: str) -> dict:
    detail = repository.get_incident_detail(incident_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return detail


@router.get("/{incident_id}/report")
def download_incident_report(incident_id: str) -> Response:
    """
    Generate and download a PDF incident report.

    The report is generated from the persisted incident detail so that
    the downloadable report uses the same evidence and analysis shown
    by the ChroniX dashboard.
    """

    detail = repository.get_incident_detail(incident_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    analysis = detail.get("analysis") or {}
    evidence = detail.get("evidence") or []
    relationships = detail.get("relationships") or []

    timeline = analysis.get("timeline") or []

    # ---------------------------------------------------------
    # Classification counts
    # ---------------------------------------------------------

    counts = {
        "FACT": 0,
        "INFERENCE": 0,
        "CONFLICT": 0,
        "UNKNOWN": 0,
    }

    for event in timeline:
        classification = str(
            event.get("classification", "UNKNOWN")
        ).upper()

        if classification in counts:
            counts[classification] += 1
        else:
            counts["UNKNOWN"] += 1

    # ---------------------------------------------------------
    # PDF setup
    # ---------------------------------------------------------

    buffer = BytesIO()

    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = styles["Title"]
    heading_style = styles["Heading2"]
    body_style = styles["BodyText"]

    story = []

    # ---------------------------------------------------------
    # Header
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "CHRONIX",
            title_style,
        )
    )

    story.append(
        Paragraph(
            "Evidence-Driven Incident Intelligence",
            body_style,
        )
    )

    story.append(Spacer(1, 8))

    story.append(
        Paragraph(
            "Incident Report",
            heading_style,
        )
    )

    story.append(Spacer(1, 10))

    # ---------------------------------------------------------
    # Incident overview
    # ---------------------------------------------------------

    incident_title = analysis.get(
        "incident_title",
        detail.get("title", "Incident"),
    )

    story.append(
        Paragraph(
            f"<b>Incident:</b> {incident_title}",
            body_style,
        )
    )

    story.append(
        Paragraph(
            f"<b>Incident ID:</b> {incident_id}",
            body_style,
        )
    )

    summary = analysis.get(
        "summary",
        "No summary available.",
    )

    story.append(
        Paragraph(
            f"<b>Summary:</b> {summary}",
            body_style,
        )
    )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Evidence classification
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Evidence Classification",
            heading_style,
        )
    )

    classification_table = Table(
        [
            [
                "FACT",
                "INFERENCE",
                "CONFLICT",
                "UNKNOWN",
            ],
            [
                str(counts["FACT"]),
                str(counts["INFERENCE"]),
                str(counts["CONFLICT"]),
                str(counts["UNKNOWN"]),
            ],
        ],
        colWidths=[40 * mm] * 4,
    )

    classification_table.setStyle(
        TableStyle(
            [
                (
                    "GRID",
                    (0, 0),
                    (-1, -1),
                    0.5,
                    colors.grey,
                ),
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, 0),
                    colors.lightgrey,
                ),
                (
                    "ALIGN",
                    (0, 0),
                    (-1, -1),
                    "CENTER",
                ),
                (
                    "FONTNAME",
                    (0, 0),
                    (-1, 0),
                    "Helvetica-Bold",
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(classification_table)
    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Root cause assessment
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Root Cause Assessment",
            heading_style,
        )
    )

    root_cause = analysis.get("root_cause") or {}

    if isinstance(root_cause, dict):
        root_status = root_cause.get(
            "status",
            analysis.get(
                "root_cause_status",
                "NOT CONFIRMED",
            ),
        )

        root_explanation = root_cause.get(
            "explanation",
            "Available evidence is insufficient to establish a confirmed causal chain.",
        )

    else:
        root_status = analysis.get(
            "root_cause_status",
            "NOT CONFIRMED",
        )

        root_explanation = str(root_cause)

    story.append(
        Paragraph(
            f"<b>Status:</b> {root_status}",
            body_style,
        )
    )

    story.append(
        Paragraph(
            f"<b>Assessment:</b> {root_explanation}",
            body_style,
        )
    )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Timeline
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Incident Timeline",
            heading_style,
        )
    )

    timeline_rows = [
        [
            "Time",
            "Classification",
            "Event",
            "Source",
        ]
    ]

    for event in timeline:
        timestamp = event.get(
            "timestamp",
            "-",
        )

        classification = event.get(
            "classification",
            "UNKNOWN",
        )

        event_text = event.get(
            "event",
            "-",
        )

        source = event.get(
            "source",
            event.get(
                "source_name",
                "-",
            ),
        )

        timeline_rows.append(
            [
                str(timestamp),
                str(classification),
                str(event_text),
                str(source),
            ]
        )

    if len(timeline_rows) > 1:
        timeline_table = Table(
            timeline_rows,
            colWidths=[
                28 * mm,
                28 * mm,
                82 * mm,
                35 * mm,
            ],
            repeatRows=1,
        )

        timeline_table.setStyle(
            TableStyle(
                [
                    (
                        "GRID",
                        (0, 0),
                        (-1, -1),
                        0.4,
                        colors.grey,
                    ),
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.lightgrey,
                    ),
                    (
                        "FONTNAME",
                        (0, 0),
                        (-1, 0),
                        "Helvetica-Bold",
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "FONTSIZE",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        5,
                    ),
                ]
            )
        )

        story.append(timeline_table)

    else:
        story.append(
            Paragraph(
                "No timeline events available.",
                body_style,
            )
        )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Evidence relationships
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Evidence Relationships",
            heading_style,
        )
    )

    if relationships:
        for relationship in relationships:
            source = relationship.get(
                "source_evidence_id",
                relationship.get(
                    "source",
                    "-",
                ),
            )

            target = relationship.get(
                "target_evidence_id",
                relationship.get(
                    "target",
                    "-",
                ),
            )

            relationship_type = relationship.get(
                "relationship_type",
                "-",
            )

            confidence = relationship.get(
                "confidence",
                "-",
            )

            story.append(
                Paragraph(
                    f"<b>{source}</b> → <b>{target}</b> "
                    f"({relationship_type}, confidence: {confidence})",
                    body_style,
                )
            )

    else:
        story.append(
            Paragraph(
                "No evidence relationships recorded.",
                body_style,
            )
        )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Missing evidence
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Missing Evidence",
            heading_style,
        )
    )

    missing_evidence = analysis.get(
        "missing_evidence",
        [],
    )

    if missing_evidence:
        for item in missing_evidence:
            story.append(
                Paragraph(
                    f"• {item}",
                    body_style,
                )
            )
    else:
        story.append(
            Paragraph(
                "No missing evidence items recorded.",
                body_style,
            )
        )

    story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Investigation recommendations
    # ---------------------------------------------------------

    recommendations = analysis.get(
        "investigation_recommendations",
        [],
    )

    if recommendations:
        story.append(
            Paragraph(
                "Investigation Recommendations",
                heading_style,
            )
        )

        for item in recommendations:
            story.append(
                Paragraph(
                    f"• {item}",
                    body_style,
                )
            )

        story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Local intelligence
    # ---------------------------------------------------------

    llm = (
        analysis.get("llm_enrichment")
        or analysis.get("local_intelligence")
        or {}
    )

    if isinstance(llm, dict) and llm:
        story.append(
            Paragraph(
                "Local Intelligence",
                heading_style,
            )
        )

        llm_summary = llm.get(
            "incident_summary",
            llm.get(
                "summary",
                "",
            ),
        )

        if llm_summary:
            story.append(
                Paragraph(
                    f"<b>AI Summary:</b> {llm_summary}",
                    body_style,
                )
            )

        probable_causes = llm.get(
            "probable_causes",
            [],
        )

        if probable_causes:
            story.append(
                Paragraph(
                    "<b>Probable Causes:</b>",
                    body_style,
                )
            )

            for cause in probable_causes:
                story.append(
                    Paragraph(
                        f"• {cause}",
                        body_style,
                    )
                )

        uncertainty = llm.get(
            "uncertainty",
            [],
        )

        if uncertainty:
            story.append(
                Paragraph(
                    "<b>Uncertainty:</b>",
                    body_style,
                )
            )

            if isinstance(uncertainty, list):
                for item in uncertainty:
                    story.append(
                        Paragraph(
                            f"• {item}",
                            body_style,
                        )
                    )
            else:
                story.append(
                    Paragraph(
                        str(uncertainty),
                        body_style,
                    )
                )

        story.append(Spacer(1, 12))

    # ---------------------------------------------------------
    # Evidence traceability
    # ---------------------------------------------------------

    story.append(
        Paragraph(
            "Evidence Traceability",
            heading_style,
        )
    )

    if evidence:
        for item in evidence:
            evidence_id = item.get(
                "evidence_id",
                "-",
            )

            source = item.get(
                "source_name",
                item.get(
                    "source",
                    "-",
                ),
            )

            event = item.get(
                "event",
                "-",
            )

            story.append(
                Paragraph(
                    f"<b>{evidence_id}</b> — "
                    f"{source} — {event}",
                    body_style,
                )
            )
    else:
        story.append(
            Paragraph(
                "No persisted evidence records available.",
                body_style,
            )
        )

    story.append(Spacer(1, 16))

    story.append(
        Paragraph(
            "Generated by ChroniX — Evidence-Driven Incident Intelligence",
            body_style,
        )
    )

    # ---------------------------------------------------------
    # Generate PDF
    # ---------------------------------------------------------

    document.build(story)

    buffer.seek(0)

    filename = (
        f"chronix-incident-report-{incident_id}.pdf"
    )

    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        },
    )


@router.post("/active/reset")
def reset_active_incident() -> dict[str, object]:
    active_incident.clear()

    return {
        "status": "reset",
        "count": 0,
    }


@router.get("/active/intelligence")
def get_active_intelligence() -> dict[str, object]:
    analysis = active_incident.latest_analysis()

    if analysis is None:
        return {
            "status": "not_ready",
            "analysis": None,
        }

    return {
        "status": "ready",
        "analysis": analysis,
    }


@router.post(
    "/analyze-active",
    response_model=IncidentAnalysis,
)
def analyze_active_incident() -> IncidentAnalysis:
    return active_incident.refresh()


@router.get("/active/graph")
def get_active_graph() -> dict[str, object]:
    analysis = active_incident.latest_analysis()

    if not analysis:
        return {
            "incident_id": active_incident.incident_id,
            "nodes": [],
            "edges": [],
        }

    nodes = [
        {
            "id": event.source_id,
            "label": event.event,
            "timestamp": (
                event.timestamp.isoformat()
                if event.timestamp
                else None
            ),
            "source": event.source,
            "classification": event.classification,
            "raw_evidence": event.raw_evidence,
        }
        for event in analysis.timeline
    ]

    edges = [
        {
            "id": rel.relationship_id,
            "source": rel.source_evidence_id,
            "target": rel.target_evidence_id,
            "relationship_type": rel.relationship_type,
            "confidence": rel.confidence,
            "basis": rel.basis,
            "status": rel.status,
        }
        for rel in analysis.relationships
    ]

    return {
        "incident_id": active_incident.incident_id,
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/{incident_id}/graph")
def get_incident_graph(incident_id: str) -> dict[str, object]:
    detail = repository.get_incident_detail(incident_id)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    analysis = detail.get("analysis")

    nodes = [
        {
            "id": item["evidence_id"],
            "label": item["event"],
            "timestamp": item.get("timestamp"),
            "source": item["source_name"],
            "classification": item.get(
                "classification",
                "FACT",
            ),
            "raw_evidence": item["raw_evidence"],
        }
        for item in detail.get("evidence", [])
    ]

    edges = detail.get("relationships", [])

    if (
        analysis
        and "relationships" in analysis
        and not edges
    ):
        edges = analysis["relationships"]

    return {
        "incident_id": incident_id,
        "nodes": nodes,
        "edges": edges,
    }