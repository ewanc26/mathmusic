<!-- Lists saved projects and opens one. -->
<script lang="ts">
  import { X } from "@lucide/svelte";
  import { api } from "$lib/api";
  import { daw } from "$lib/daw.svelte";
  import { toast } from "$lib/toast.svelte";
  import { transport } from "$lib/transport.svelte";
  import type { Project } from "$lib/types";
  import { view } from "$lib/view.svelte";

  let dialog = $state<HTMLDialogElement>();
  let folder = $state("");
  let items = $state<{ name: string; modified: string }[] | null>(null);
  let error = $state("");

  export async function show() {
    items = null;
    error = "";
    dialog?.showModal();
    try {
      const data = await api.get<{ projects: { name: string; modified: string }[]; folder: string }>("/api/projects");
      folder = data.folder;
      items = data.projects;
    } catch (e) {
      error = (e as Error).message;
    }
  }

  async function open(name: string) {
    if (daw.dirty && !confirm("Discard unsaved changes and open this project?")) return;
    try {
      const project = await api.get<Project>(`/api/projects/${encodeURIComponent(name)}`);
      dialog?.close();
      transport.pause();
      daw.load(project);
      view.fit(daw.songLength);
      toast.show(`Opened “${name}”.`, "ok");
    } catch (e) {
      toast.show((e as Error).message, "err");
    }
  }
</script>

<dialog
  bind:this={dialog}
  class="m-auto w-[min(560px,calc(100vw-32px))] rounded-2xl border border-line bg-panel-2 px-5 py-4 text-ink"
>
  <div class="flex items-center justify-between">
    <h2 class="text-base font-semibold">Open project</h2>
    <button class="icon-btn" type="button" aria-label="Close" onclick={() => dialog?.close()}><X size={15} /></button>
  </div>
  <p class="hint mt-1">Saved in <code class="font-mono">{folder}</code></p>
  <ul class="mt-2 grid max-h-[50vh] gap-1.5 overflow-auto">
    {#if error}
      <li class="text-xs text-bad">{error}</li>
    {:else if items === null}
      <li class="hint">Loading…</li>
    {:else}
      {#each items as item (item.name)}
        <li>
          <button
            class="flex w-full justify-between gap-3 rounded-[10px] border border-line bg-panel px-3 py-2 text-left hover:border-neon-cyan"
            type="button"
            onclick={() => open(item.name)}
          >
            <strong>{item.name}</strong>
            <span class="hint">{new Date(item.modified).toLocaleString()}</span>
          </button>
        </li>
      {:else}
        <li class="hint">No saved projects yet. Name your project and press Save.</li>
      {/each}
    {/if}
  </ul>
</dialog>
