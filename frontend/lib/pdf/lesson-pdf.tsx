import { Document, Page, StyleSheet, Text, View, pdf, type DocumentProps } from "@react-pdf/renderer";
import type { ReactElement } from "react";

import { PlainText } from "@/lib/plain-text";
import type { LessonPageContent, LessonSection } from "@/lib/types";

const styles = StyleSheet.create({
  page: { padding: 36, fontSize: 10, fontFamily: "Helvetica", lineHeight: 1.4 },
  title: { fontSize: 22, marginBottom: 12, fontFamily: "Helvetica-Bold" },
  pageTitle: { fontSize: 16, marginBottom: 8, fontFamily: "Helvetica-Bold" },
  heading: { fontSize: 12, marginTop: 10, marginBottom: 3, fontFamily: "Helvetica-Bold" },
  card: { marginTop: 4, padding: 6, borderWidth: 0.5, borderColor: "#bbb", borderRadius: 3 },
  label: { fontFamily: "Helvetica-Bold" },
  muted: { color: "#555" },
  mono: { fontFamily: "Courier" },
});

const text = (value: string) => PlainText.of(value);

/** The reading pages of a lesson (introduction, core, advanced) as a PDF, built from the structured page content. */
export class LessonPdf {
  static element(title: string, pages: LessonPageContent[]): ReactElement<DocumentProps> {
    return (
      <Document title={text(title)}>
        {pages.map((page, n) => (
          <Page key={page.key} size="A4" style={styles.page} wrap>
            {n === 0 ? <Text style={styles.title}>{text(title)}</Text> : null}
            <Text style={styles.pageTitle}>{text(page.title)}</Text>
            {page.sections.flatMap((section) => LessonPdf.section(section))}
            <Text style={styles.heading}>Summary</Text>
            <Text>{text(page.summary)}</Text>
          </Page>
        ))}
      </Document>
    );
  }

  static async blob(title: string, pages: LessonPageContent[]): Promise<Blob> {
    return pdf(LessonPdf.element(title, pages)).toBlob();
  }

  /** The reading pages of `LESSON.pages`, in the order a learner reads them (a page the data lacks is left out). */
  static pagesOf(data: { pages?: Record<string, LessonPageContent> }): LessonPageContent[] {
    return ["introduction", "core", "advanced"].flatMap((key) => (data.pages?.[key] ? [data.pages[key]] : []));
  }

  private static section(section: LessonSection): ReactElement[] {
    const id = section.id;
    const parts: ReactElement[] = [
      <Text key={`${id}-h`} style={styles.heading}>{text(section.heading)}</Text>,
      <Text key={`${id}-b`}>{text(section.body)}</Text>,
    ];
    section.key_points.forEach((point, i) => parts.push(<Text key={`${id}-k${i}`}>• {text(point)}</Text>));
    section.formulas.forEach((f, i) =>
      parts.push(
        <View key={`${id}-f${i}`} style={styles.card} wrap={false}>
          <Text style={styles.mono}>{text(f.latex)}</Text>
          <Text style={styles.muted}>{text(f.explanation)}</Text>
        </View>,
      ),
    );
    section.worked_examples.forEach((ex, i) =>
      parts.push(
        <View key={`${id}-w${i}`} style={styles.card} wrap={false}>
          <Text style={styles.label}>Example: {text(ex.problem)}</Text>
          <Text>{text(ex.solution)}</Text>
        </View>,
      ),
    );
    section.code_snippets.forEach((c, i) =>
      parts.push(
        <View key={`${id}-c${i}`} style={styles.card} wrap={false}>
          <Text style={styles.mono}>{c.code}</Text>
          <Text style={styles.muted}>{text(c.explanation)}</Text>
        </View>,
      ),
    );
    section.callouts.forEach((c, i) =>
      parts.push(
        <View key={`${id}-n${i}`} style={styles.card} wrap={false}>
          <Text>
            <Text style={styles.label}>{c.kind.toUpperCase()}: </Text>
            {text(c.text)}
          </Text>
        </View>,
      ),
    );
    return parts;
  }
}
