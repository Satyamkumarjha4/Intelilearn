import { Document, Page, StyleSheet, Text, View, pdf, type DocumentProps } from "@react-pdf/renderer";
import type { ReactElement } from "react";

import { PlainText } from "@/lib/plain-text";
import type { CheatSheet, MaterialKind, PracticeSheet, RevisionSheet, Solution } from "@/lib/types";

const styles = StyleSheet.create({
  page: { padding: 36, fontSize: 10, fontFamily: "Helvetica", lineHeight: 1.4 },
  footer: { position: "absolute", bottom: 16, left: 36, right: 36, flexDirection: "row", justifyContent: "space-between", fontSize: 8, color: "#777" },
  title: { fontSize: 20, marginBottom: 4, fontFamily: "Helvetica-Bold" },
  lead: { marginBottom: 12, color: "#444" },
  heading: { fontSize: 13, marginTop: 12, marginBottom: 4, fontFamily: "Helvetica-Bold" },
  card: { marginBottom: 6, padding: 6, borderWidth: 0.5, borderColor: "#bbb", borderRadius: 3 },
  label: { fontFamily: "Helvetica-Bold" },
  muted: { color: "#555" },
  mono: { fontFamily: "Courier" },
});

type Rendered = { title: string; body: ReactElement[] };

const text = (value: string) => PlainText.of(value);

/** A study sheet as a PDF document, built from the structured JSON (no browser rendering involved). */
export class StudyPdf {
  static element(
    kind: MaterialKind,
    content: unknown,
    solutions: Record<string, Solution> = {},
  ): ReactElement<DocumentProps> {
    const { title, body } = StudyPdf.render(kind, content, solutions);
    return (
      <Document title={title}>
        <Page size="A4" style={styles.page} wrap>
          <Text style={styles.title}>{title}</Text>
          {body}
        <View fixed style={styles.footer}>
          <Text>Socra</Text>
          <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
        </View>
      </Page>
      </Document>
    );
  }

  static async blob(kind: MaterialKind, content: unknown, solutions: Record<string, Solution> = {}): Promise<Blob> {
    return pdf(StudyPdf.element(kind, content, solutions)).toBlob();
  }

  private static render(kind: MaterialKind, content: unknown, solutions: Record<string, Solution>): Rendered {
    if (kind === "cheat_sheet") return StudyPdf.cheat(content as CheatSheet);
    if (kind === "revision_sheet") return StudyPdf.revision(content as RevisionSheet);
    return StudyPdf.practice(content as PracticeSheet, solutions);
  }

  private static cheat(sheet: CheatSheet): Rendered {
    const body: ReactElement[] = [<Text key="summary" style={styles.lead}>{text(sheet.summary)}</Text>];
    sheet.sections.forEach((section, s) => {
      body.push(<Text key={`h${s}`} style={styles.heading}>{text(section.heading)}</Text>);
      section.items.forEach((item, i) => {
        body.push(
          <View key={`i${s}-${i}`} style={styles.card} wrap={false}>
            <Text style={styles.label}>{text(item.label)}</Text>
            <Text>{text(item.content)}</Text>
            {item.formula ? <Text style={styles.mono}>{text(item.formula)}</Text> : null}
            {item.variables.map((v) => (
              <Text key={v.symbol} style={styles.muted}>
                {text(v.symbol)}: {text(v.meaning)}
              </Text>
            ))}
            {item.when_to_use ? <Text style={styles.muted}>Use when: {text(item.when_to_use)}</Text> : null}
          </View>,
        );
      });
    });
    return { title: text(sheet.title), body };
  }

  private static revision(sheet: RevisionSheet): Rendered {
    const body: ReactElement[] = [<Text key="overview" style={styles.lead}>{text(sheet.overview)}</Text>];
    sheet.subtopics.forEach((sub, n) => {
      body.push(<Text key={`t${n}`} style={styles.heading}>{text(sub.title)}</Text>);
      body.push(<Text key={`s${n}`}>{text(sub.summary)}</Text>);
      sub.key_points.forEach((point, i) => body.push(<Text key={`k${n}-${i}`}>• {text(point)}</Text>));
      sub.worked_examples.forEach((ex, i) => {
        body.push(
          <View key={`w${n}-${i}`} style={styles.card} wrap={false}>
            <Text style={styles.label}>Example: {text(ex.problem)}</Text>
            <Text>{text(ex.solution)}</Text>
          </View>,
        );
      });
      sub.common_mistakes.forEach((m, i) => body.push(<Text key={`m${n}-${i}`} style={styles.muted}>Mistake: {text(m)}</Text>));
    });
    if (sheet.final_tips.length) {
      body.push(<Text key="tips" style={styles.heading}>Final tips</Text>);
      sheet.final_tips.forEach((tip, i) => body.push(<Text key={`f${i}`}>• {text(tip)}</Text>));
    }
    return { title: text(sheet.title), body };
  }

  private static practice(sheet: PracticeSheet, solutions: Record<string, Solution>): Rendered {
    const body: ReactElement[] = [<Text key="instr" style={styles.lead}>{text(sheet.instructions)}</Text>];
    sheet.questions.forEach((q, n) => {
      const solution = solutions[q.id];
      body.push(
        <View key={q.id} style={styles.card} wrap={false}>
          <Text style={styles.label}>
            {n + 1}. {text(q.question)} ({q.marks} marks)
          </Text>
          {q.options?.map((option, i) => <Text key={i}>{String.fromCharCode(65 + i)}. {text(option)}</Text>)}
          {solution ? <Text style={styles.muted}>{StudyPdf.solutionLine(q.options, solution)}</Text> : null}
        </View>,
      );
    });
    return { title: text(sheet.title), body };
  }

  private static solutionLine(options: string[] | undefined, solution: Solution): string {
    if (solution.correct_index !== undefined && options) return `Answer: ${String.fromCharCode(65 + solution.correct_index)}`;
    if (solution.answer !== undefined) return `Answer: ${solution.answer}${solution.unit ? ` ${solution.unit}` : ""}`;
    return `Answer: ${text(solution.model_answer ?? solution.reference_solution ?? "")}`;
  }
}
