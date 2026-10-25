"use client";

import { FlaskConicalIcon, PlusIcon } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/console/empty-state";
import { ErrorState } from "@/components/console/error-state";
import { ModelDialog, type ModelDialogTarget } from "@/components/console/models/model-dialog";
import { ModelsTable } from "@/components/console/models/models-table";
import { ProviderCard } from "@/components/console/models/provider-card";
import { ProviderDialog } from "@/components/console/models/provider-dialog";
import { useModelTests } from "@/components/console/models/use-model-tests";
import { PageHeader } from "@/components/console/page-header";
import { CardSkeleton, KpiRowSkeleton } from "@/components/console/skeletons";
import { useConsoleQuery } from "@/components/console/use-console-query";
import { useNow } from "@/components/lessons/use-now";
import { Button } from "@/components/ui/button";
import { consoleQueries } from "@/lib/console-queries";
import { ModelCatalog } from "@/lib/model-catalog";
import type { ConsoleProvider } from "@/lib/types";

/** The Models page: the providers (whose keys are set), the models, and the tests that say whether each one works. */
export function ModelsView() {
  const providers = useConsoleQuery(consoleQueries.providers());
  const models = useConsoleQuery(consoleQueries.models());
  const tests = useModelTests();
  const now = new Date(useNow(true, 30_000));
  const [editingProvider, setEditingProvider] = useState<ConsoleProvider | null>(null);
  const [editingModel, setEditingModel] = useState<ModelDialogTarget>(null);

  const rows = models.data ?? [];
  const header = (
    <PageHeader
      title="Models"
      description="Providers and the models Socra can use. API keys stay in the server environment and are never shown here."
      actions={
        <>
          <Button variant="outline" disabled={tests.running || rows.length === 0} onClick={() => void tests.testAll(rows)}>
            <FlaskConicalIcon /> {tests.running ? "Testing…" : "Test all models"}
          </Button>
          <Button disabled={!providers.data?.length} onClick={() => setEditingModel("new")}>
            <PlusIcon /> Add model
          </Button>
        </>
      }
    />
  );

  if ((providers.error && !providers.data) || (models.error && !models.data)) {
    return (
      <>
        {header}
        <ErrorState
          message="The providers and models could not be loaded."
          onRetry={() => {
            void providers.refetch();
            void models.refetch();
          }}
        />
      </>
    );
  }
  if (!providers.data || !models.data) {
    return (
      <div aria-busy="true">
        {header}
        <KpiRowSkeleton />
        <div className="mt-4">
          <CardSkeleton />
        </div>
      </div>
    );
  }

  return (
    <div>
      {header}
      <div className="grid grid-cols-4 gap-3 max-[1180px]:grid-cols-2 max-[560px]:grid-cols-1">
        {providers.data.map((provider) => (
          <ProviderCard key={provider.key} provider={provider} onEdit={() => setEditingProvider(provider)} />
        ))}
      </div>

      <section aria-label="Models" className="mt-4 rounded-2xl border bg-card shadow-card">
        <div className="px-[18px] pt-4">
          <h2 className="font-sans text-base font-extrabold">Models</h2>
          <p className="text-[13px] font-semibold text-muted-foreground">&ldquo;Test&rdquo; sends one tiny request and checks structured output</p>
        </div>
        <div className="px-[18px] pt-2 pb-4">
          {rows.length === 0 ? (
            <EmptyState icon={FlaskConicalIcon} title="No models yet" description="Add a model to give the lesson steps something to call." />
          ) : (
            <ModelsTable models={ModelCatalog.sorted(rows)} testing={tests.testing} now={now} onTest={tests.testOne} onEdit={setEditingModel} />
          )}
        </div>
      </section>

      <ProviderDialog provider={editingProvider} onClose={() => setEditingProvider(null)} />
      <ModelDialog target={editingModel} providers={providers.data} onClose={() => setEditingModel(null)} />
    </div>
  );
}
