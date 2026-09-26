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
    """Build an incident investigation report from persisted incident detail."""
    import os
    from collections import Counter
    from html import escape

    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen import canvas as reportlab_canvas
    from reportlab.platypus import PageBreak

    detail = repository.get_incident_detail(incident_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    analysis = detail.get("analysis") or {}
    evidence = detail.get("evidence") or []
    relationships_raw = detail.get("relationships") or []
    relationship_map = {}
    for relation in relationships_raw:
        key = (
            relation.get("source_evidence_id"), relation.get("target_evidence_id"),
            relation.get("relationship_type"), relation.get("status"), relation.get("basis"),
        )
        relationship_map.setdefault(key, relation)
    relationships = list(relationship_map.values())
    timeline = sorted(
        analysis.get("timeline") or [],
        key=lambda event: (not bool(event.get("timestamp")), event.get("timestamp") or "", event.get("order", 0)),
    )
    timeline_class_counts = Counter(
        str(event.get("classification") or "UNKNOWN").upper() for event in timeline
    )
    facts = analysis.get("facts") or []
    inferences = analysis.get("inferences") or []
    conflicts = analysis.get("conflicts") or []
    unknowns = analysis.get("unknowns") or []
    missing_evidence = analysis.get("missing_evidence") or []
    root_status = analysis.get("root_cause_status") or detail.get("root_cause_status") or "NOT CONFIRMED"
    root_basis = analysis.get("root_cause_basis") or "Available evidence is insufficient or contradictory to establish a causal chain."
    if root_status == "NOT CONFIRMED" and "insufficient or contradictory" not in root_basis.lower():
        root_explanation = f"Available evidence is insufficient or contradictory to establish a causal chain. {root_basis}"
    else:
        root_explanation = root_basis
    title = analysis.get("incident_title") or detail.get("incident_title") or "Incident"
    incident_status = "Active" if str(detail.get("status", "")).lower() == "active" else "Historical"
    evidence_by_id = {str(item.get("evidence_id") or item.get("source_id")): item for item in evidence}

    def safe(value: object) -> str:
        return escape(str(value if value not in (None, "") else "Not recorded"), quote=False)

    def clock_time(event: dict) -> str:
        value = event.get("timestamp")
        if not value:
            return "time not recorded"
        value = str(value)
        try:
            from datetime import datetime
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            return value

    def event_text(event: dict) -> str:
        return str(event.get("event") or event.get("raw_evidence") or "Evidence received")

    def source_ids_for_event(event: dict) -> list[str]:
        source_names = set(event.get("sources") or [])
        supporting_text = set(event.get("supporting_evidence") or [])
        matched = [
            item for item in evidence
            if str(item.get("raw_evidence") or "") in supporting_text
            and (not source_names or item.get("source_name") in source_names)
        ]
        ids = list(dict.fromkeys(
            str(item.get("evidence_id") or item.get("source_id"))
            for item in matched if item.get("evidence_id") or item.get("source_id")
        ))
        representative_id = str(event.get("source_id") or "")
        if representative_id in evidence_by_id and representative_id not in ids:
            ids.insert(0, representative_id)
        return ids

    def section(label: str) -> None:
        story.append(Spacer(1, 8))
        story.append(Paragraph(safe(label), styles["Heading2"]))
        story.append(Spacer(1, 4))

    def bullet(value: object) -> None:
        story.append(Paragraph(f"- {safe(value)}", body_style))
        story.append(Spacer(1, 2))

    page_size = A4
    page_width, page_height = page_size
    left_margin = right_margin = 18 * mm

    class NumberedCanvas(reportlab_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.saved_page_states = []

        def showPage(self):
            self.saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total_pages = len(self.saved_page_states)
            for page_number, state in enumerate(self.saved_page_states, start=1):
                self.__dict__.update(state)
                self.saveState()
                self.setStrokeColor(colors.HexColor("#d5ddd4"))
                self.setLineWidth(0.5)
                self.line(left_margin, 16 * mm, page_width - right_margin, 16 * mm)
                self.setFillColor(colors.HexColor("#65716b"))
                self.setFont("Helvetica", 7)
                self.drawString(left_margin, 10 * mm, "Generated by ChroniX - Evidence-Driven Incident Intelligence")
                self.drawRightString(page_width - right_margin, 10 * mm, f"Page {page_number} of {total_pages}")
                self.setFont("Helvetica-Bold", 7)
                self.drawRightString(page_width - right_margin, page_height - 11 * mm, f"CHRONIX / {incident_id[:8]}")
                self.restoreState()
                reportlab_canvas.Canvas.showPage(self)
            reportlab_canvas.Canvas.save(self)

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=page_size, rightMargin=right_margin, leftMargin=left_margin,
        topMargin=20 * mm, bottomMargin=21 * mm,
        title=f"ChroniX Incident Investigation Report - {title}", author="ChroniX",
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ChronixBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9, leading=13, spaceAfter=3,
    )
    small_style = ParagraphStyle("ChronixSmall", parent=body_style, fontSize=7.2, leading=9)
    metric_style = ParagraphStyle("ChronixMetric", parent=body_style, fontName="Helvetica-Bold", fontSize=15, leading=18, alignment=1)
    label_style = ParagraphStyle("ChronixLabel", parent=small_style, fontName="Helvetica-Bold", alignment=1)
    story = [
        Paragraph("CHRONIX", styles["Title"]),
        Paragraph("Evidence-Driven Incident Intelligence", body_style),
        Spacer(1, 6),
        Paragraph("INCIDENT INVESTIGATION REPORT", styles["Heading1"]),
        Paragraph(safe(title), styles["Heading2"]),
        Paragraph(f"<b>Incident ID:</b> {safe(incident_id)}", small_style),
        Paragraph(f"<b>Status:</b> {safe(incident_status)}", body_style),
    ]

    status_box = Table(
        [[Paragraph("ROOT CAUSE", label_style), Paragraph("STATUS", label_style)],
         [Paragraph("Assessment", small_style), Paragraph(safe(root_status), metric_style)]],
        colWidths=[87 * mm, 87 * mm], hAlign="LEFT",
    )
    status_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f1f4ec")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#b9c6b5")),
        ("LINEBEFORE", (1, 0), (1, -1), 0.7, colors.HexColor("#b9c6b5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([status_box, Spacer(1, 5), Paragraph(safe(root_explanation), small_style)])

    section("Evidence to Reconstructed Events")
    flow_data = [[
        Paragraph("RAW EVIDENCE SIGNALS", label_style), Paragraph(">", metric_style),
        Paragraph("RECONSTRUCTED TIMELINE EVENTS", label_style), Paragraph(">", metric_style),
        Paragraph("TRACEABLE INCIDENT STORY", label_style),
    ], [
        Paragraph(str(len(evidence)), metric_style), Paragraph("", small_style),
        Paragraph(str(len(timeline)), metric_style), Paragraph("", small_style),
        Paragraph("Source-linked", small_style),
    ]]
    flow = Table(flow_data, colWidths=[47 * mm, 8 * mm, 47 * mm, 8 * mm, 64 * mm], hAlign="LEFT")
    flow.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8f4")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d5ddd4")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#e0e5dd")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(flow)
    story.append(Paragraph(
        "Multiple evidence signals may support the same reconstructed timeline event.", small_style,
    ))

    section("Executive Summary")
    deterministic_summary = analysis.get("summary")
    if deterministic_summary:
        story.append(Paragraph(safe(deterministic_summary), body_style))
    elif timeline:
        story.append(Paragraph(
            f"The reconstructed sequence begins with {safe(event_text(timeline[0]))} at {safe(clock_time(timeline[0]))}.",
            body_style,
        ))

    action_words = ("restart", "deploy", "rollback", "failover", "mitigat", "scale", "switch over")
    recovery_words = ("normal", "decreas", "recover", "restor", "healthy", "resolved", "returned to baseline")
    actions = [(index, event) for index, event in enumerate(timeline) if any(word in event_text(event).lower() for word in action_words)]
    recoveries = [(index, event) for index, event in enumerate(timeline) if any(word in event_text(event).lower() for word in recovery_words)]
    recovery_action_pair = next((
        (index, action) for index, action in reversed(actions)
        if any(recovery_index > index for recovery_index, _ in recoveries)
    ), None)
    later_recoveries = [event for recovery_index, event in recoveries if recovery_action_pair and recovery_index > recovery_action_pair[0]]

    selected = {}
    if timeline:
        selected[id(timeline[0])] = timeline[0]
    for event in timeline:
        if str(event.get("classification", "")).upper() == "INFERENCE":
            selected[id(event)] = event
            break
    if recovery_action_pair:
        selected[id(recovery_action_pair[1])] = recovery_action_pair[1]
    for event in later_recoveries:
        selected[id(event)] = event
    selected_events = sorted(selected.values(), key=lambda event: (not bool(event.get("timestamp")), event.get("timestamp") or "", event.get("order", 0)))
    if selected_events:
        sequence = "; ".join(f"{event_text(event)} ({clock_time(event)})" for event in selected_events)
        story.append(Paragraph(f"The recorded sequence includes {safe(sequence)}.", body_style))
    if inferences:
        story.append(Paragraph(
            "Suspected explanations remain inferences; event order alone does not establish causation.", body_style,
        ))
    if root_status == "NOT CONFIRMED":
        story.append(Paragraph(
            "The available evidence establishes the recorded sequence, but is insufficient or contradictory to confirm a single root cause.",
            body_style,
        ))

    section("Incident Timeline")
    timeline_rows = [["Time", "Event", "Classification", "Supporting evidence"]]
    for event in timeline:
        ids = source_ids_for_event(event)
        timeline_rows.append([
            Paragraph(safe(clock_time(event)), small_style),
            Paragraph(safe(event_text(event)), body_style),
            Paragraph(safe(str(event.get("classification") or "UNKNOWN").upper()), small_style),
            Paragraph(safe(", ".join(ids) if ids else "No evidence ID recorded"), small_style),
        ])
    if len(timeline_rows) > 1:
        timeline_table = Table(timeline_rows, colWidths=[23 * mm, 67 * mm, 29 * mm, 55 * mm], repeatRows=1, hAlign="LEFT")
        timeline_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(timeline_table)
    else:
        story.append(Paragraph("No reconstructed timeline events are available.", body_style))

    story.append(PageBreak())
    section("Classification Summary")
    class_order = ("FACT", "INFERENCE", "CONFLICT", "UNKNOWN")
    class_rows = [["Timeline event classification", *class_order], ["Events", *[str(timeline_class_counts.get(key, 0)) for key in class_order]]]
    class_table = Table(class_rows, colWidths=[49 * mm, 31.25 * mm, 31.25 * mm, 31.25 * mm, 31.25 * mm], repeatRows=1)
    class_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd3ca")),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(class_table)
    story.append(Paragraph(
        f"The timeline has {len(timeline)} events; its event classifications total {sum(timeline_class_counts.values())}. Facts and inferences are per-event classes. Conflicts and unknowns below are separate cross-event findings in the deterministic model.",
        small_style,
    ))
    finding_table = Table(
        [["Cross-event analysis findings", "Count"], ["Conflicts", str(len(conflicts))], ["Unknowns", str(len(unknowns))]],
        colWidths=[135 * mm, 39 * mm], repeatRows=1,
    )
    finding_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f4ec")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([Spacer(1, 5), finding_table])

    section("Response and Recovery")
    if recovery_action_pair and later_recoveries:
        action = recovery_action_pair[1]
        recovery_text = "; ".join(f"{event_text(event)} ({clock_time(event)})" for event in later_recoveries)
        story.append(Paragraph(
            f"The timeline records {safe(event_text(action))} at {safe(clock_time(action))}. Recovery signals were observed afterward: {safe(recovery_text)}. The available evidence does not establish that the action directly caused recovery.",
            body_style,
        ))
    elif later_recoveries:
        story.append(Paragraph(
            f"Recovery signals recorded in the timeline: {safe('; '.join(event_text(event) + ' (' + clock_time(event) + ')' for event in later_recoveries))}. The evidence does not establish what caused recovery.",
            body_style,
        ))
    else:
        story.append(Paragraph("The reconstructed timeline does not identify a distinct recovery sequence.", body_style))

    section("Root Cause Assessment")
    cause_box = Table(
        [[Paragraph("STATUS", label_style), Paragraph(safe(root_status), metric_style)],
         [Paragraph("ASSESSMENT", label_style), Paragraph(safe(root_explanation), body_style)]],
        colWidths=[36 * mm, 138 * mm], hAlign="LEFT",
    )
    cause_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8f4")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#b9c6b5")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.45, colors.HexColor("#d5ddd4")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(cause_box)

    section("Established by Evidence")
    established = [event for event in timeline if str(event.get("classification") or "").upper() == "FACT"]
    if established:
        for event in established:
            bullet(f"{clock_time(event)} - {event_text(event)}")
    else:
        story.append(Paragraph("No timeline events are classified as FACT.", body_style))

    section("Not Established")
    not_established = [*(f"Inference only: {item}" for item in inferences), *unknowns]
    if root_status == "NOT CONFIRMED" and not not_established:
        not_established.append("A single causal chain has not been established by the available evidence.")
    if not_established:
        for item in not_established:
            bullet(item)
    else:
        story.append(Paragraph("No unresolved causal conclusions are listed by the deterministic analysis.", body_style))

    section("Evidence Summary")
    story.append(Paragraph(
        f"Evidence received: <b>{len(evidence)} raw signals</b>. Reconstructed timeline: <b>{len(timeline)} events</b>.", body_style,
    ))
    story.append(Paragraph(
        "Raw evidence can contain multiple signals that support one normalized timeline event. Event classifications and cross-event findings are reported separately above.",
        body_style,
    ))

    section("Conflicts and Uncertainty")
    if conflicts:
        story.append(Paragraph("Conflict findings", styles["Heading3"]))
        for item in conflicts:
            bullet(item)
    if unknowns:
        story.append(Paragraph("Open unknowns", styles["Heading3"]))
        for item in unknowns:
            bullet(item)
    if not conflicts and not unknowns:
        story.append(Paragraph("No cross-event conflicts or unknowns are recorded.", body_style))

    section("Missing Evidence")
    if missing_evidence:
        why = "; ".join(str(item) for item in unknowns) or str(root_explanation)
        story.append(Paragraph(
            "The deterministic analysis records the items below as missing. Item-specific rationales are not stored; each gap relates to the open assessment: " + safe(why),
            small_style,
        ))
        missing_rows = [["Evidence needed", "Why it matters"]]
        for item in missing_evidence:
            missing_rows.append([Paragraph(safe(item), body_style), Paragraph(safe(why), small_style)])
        missing_table = Table(missing_rows, colWidths=[64 * mm, 110 * mm], repeatRows=1)
        missing_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(missing_table)
    else:
        story.append(Paragraph("No missing evidence items are recorded by the deterministic analysis.", body_style))

    deterministic_recommendations = analysis.get("investigation_recommendations") or []
    enrichment = analysis.get("llm_enrichment") or {}
    ai_recommendations = enrichment.get("investigation_recommendations") or [] if isinstance(enrichment, dict) else []
    section("Next Investigation Steps")
    if deterministic_recommendations:
        for number, item in enumerate(deterministic_recommendations, start=1):
            story.append(Paragraph(f"{number}. {safe(item)}", body_style))
    else:
        story.append(Paragraph(
            "No deterministic recommendations are recorded. Local-model suggestions are identified separately below as AI-generated guidance.",
            body_style,
        ))

    section("Local AI Intelligence")
    provider = os.getenv("CHRONIX_LLM_PROVIDER", "ollama").lower()
    if provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "qwen3:4b")
        story.append(Paragraph(f"Powered by local {safe(model)} via Ollama", small_style))
    else:
        story.append(Paragraph(f"Configured enrichment provider: {safe(provider or 'not configured')}", small_style))
    story.append(Paragraph(
        "AI-generated enrichment is hypothesis-only. Deterministic analysis remains authoritative.", small_style,
    ))
    if isinstance(enrichment, dict) and enrichment:
        if enrichment.get("incident_summary"):
            story.append(Paragraph(f"<b>AI-generated interpretation:</b> {safe(enrichment['incident_summary'])}", body_style))
        ai_groups = [
            ("Probable causes - AI hypothesis", "probable_causes", "Possible explanation suggested by AI (unconfirmed): ", ". Direct causal evidence is not established."),
            ("Contributing factors - AI interpretation", "contributing_factors", "Potential contributing factor (not confirmed): ", ""),
            ("Causal relationships - AI hypotheses", "causal_relationships", "Unconfirmed AI causal hypothesis (correlation is not proof of causation): ", ". Deterministic root cause remains " + str(root_status) + "."),
            ("Evidence interpretations - AI-generated", "evidence_interpretations", "AI interpretation: ", ""),
            ("Uncertainty - AI-generated", "uncertainty", "AI-identified uncertainty: ", ""),
        ]
        for label, key, prefix, suffix in ai_groups:
            claims = enrichment.get(key) or []
            if claims:
                story.append(Paragraph(safe(label), styles["Heading3"]))
                for claim in claims:
                    description = str(claim.get("description") or "")
                    ids = claim.get("evidence_ids") or []
                    line = f"{prefix}{description}{suffix}"
                    if ids:
                        line += f" Evidence IDs: {', '.join(str(value) for value in ids)}."
                    bullet(line)
        if ai_recommendations:
            story.append(Paragraph("AI-generated recommendations", styles["Heading3"]))
            for item in ai_recommendations:
                bullet(f"AI suggestion (investigator review required): {item}")
    else:
        story.append(Paragraph(
            f"No local AI enrichment is stored for this analysis (status: {safe(analysis.get('llm_status') or 'unavailable')}).",
            body_style,
        ))

    section("Evidence Traceability")
    if timeline:
        trace_rows = [["Event", "Class", "Evidence IDs", "Source names"]]
        for event in timeline:
            ids = source_ids_for_event(event)
            source_names = event.get("sources") or ([event.get("source") or event.get("source_name")] if event.get("source") or event.get("source_name") else [])
            trace_rows.append([
                Paragraph(safe(f"{clock_time(event)} - {event_text(event)}"), small_style),
                Paragraph(safe(str(event.get("classification") or "UNKNOWN").upper()), small_style),
                Paragraph(safe(", ".join(ids) if ids else "No source ID recorded"), small_style),
                Paragraph(safe(", ".join(str(name) for name in source_names) if source_names else "Not recorded"), small_style),
            ])
        trace_table = Table(trace_rows, colWidths=[56 * mm, 20 * mm, 54 * mm, 44 * mm], repeatRows=1, hAlign="LEFT")
        trace_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(trace_table)
    else:
        story.append(Paragraph("No reconstructed events are available to trace.", body_style))

    story.append(PageBreak())
    section("Appendix A - Raw Evidence")
    story.append(Paragraph(
        "Raw source records are retained here for verification; the main report focuses on the reconstructed incident story.",
        small_style,
    ))
    raw_rows = [["Evidence ID", "Source / type", "Time / class", "Raw evidence / metadata"]]
    for item in evidence:
        metadata = item.get("metadata") or {}
        metadata_text = "; ".join(f"{key}: {value}" for key, value in metadata.items()) or "No metadata"
        source_text = f"{item.get('source_name') or item.get('source') or 'Not recorded'} / {item.get('source_type') or 'type not recorded'}"
        time_class = f"{item.get('timestamp') or 'time not recorded'} / {item.get('classification') or 'not separately classified'}"
        raw_text = item.get("raw_evidence") or item.get("event") or "No raw evidence text"
        raw_cell = f"{safe(raw_text)}<br/><br/><b>Metadata:</b> {safe(metadata_text)}"
        raw_rows.append([
            Paragraph(safe(item.get("evidence_id") or item.get("source_id")), small_style),
            Paragraph(safe(source_text), small_style),
            Paragraph(safe(time_class), small_style),
            Paragraph(raw_cell, small_style),
        ])
    if len(raw_rows) > 1:
        raw_table = Table(raw_rows, colWidths=[36 * mm, 43 * mm, 37 * mm, 58 * mm], repeatRows=1, hAlign="LEFT")
        raw_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(raw_table)
    else:
        story.append(Paragraph("No raw evidence records are available.", body_style))

    story.append(PageBreak())
    section("Appendix B - Evidence Relationships")
    story.append(Paragraph(
        "Identical persisted relationship rows are shown once. Correlation and inferred relationships are not confirmation of causality.",
        small_style,
    ))
    if relationships:
        relation_style = ParagraphStyle("ChronixRelation", parent=small_style, fontSize=6.8, leading=8)
        relation_rows = [["Source ID", "Relationship", "Target ID", "Status and basis"]]
        for relation in relationships:
            status_basis = f"{relation.get('status') or 'recorded'}: {relation.get('basis') or 'No basis recorded'}"
            relation_rows.append([
                Paragraph(safe(relation.get("source_evidence_id")), relation_style),
                Paragraph(safe(relation.get("relationship_type")), relation_style),
                Paragraph(safe(relation.get("target_evidence_id")), relation_style),
                Paragraph(safe(status_basis), relation_style),
            ])
        relation_table = Table(relation_rows, colWidths=[39 * mm, 30 * mm, 39 * mm, 66 * mm], repeatRows=1, hAlign="LEFT")
        relation_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eee6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd3ca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE", (0, 0), (-1, -1), 6.8),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        story.append(relation_table)
    else:
        story.append(Paragraph("No evidence relationships are recorded.", body_style))

    document.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    filename = f"chronix-incident-report-{incident_id}.pdf"
    return Response(
        content=buffer.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
            "incident_id": active_incident.incident_id,
        }

    return {
        "status": "ready",
        "analysis": analysis,
        "incident_id": active_incident.incident_id,
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
