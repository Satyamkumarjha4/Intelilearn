// required: Page_core
// components: Interactive_widget
function Page_core() {
  const page = LESSON.pages.core;
  return (
    <PageFrame title={page.title}>
      {page.sections.map((s) => (
        <Section key={s.id} section={s}>
          {s.id === "s1" ? <Interactive_widget /> : null}
          {s.id === "s2" ? <Figure asset="asset-1" /> : null}
        </Section>
      ))}
    </PageFrame>
  );
}
// assets: asset-1
