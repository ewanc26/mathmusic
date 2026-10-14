<!-- The DAW: top bar, arrangement and editor panel, plus keyboard shortcuts and boot. -->
<script lang="ts">
  import { onMount } from "svelte";
  import {
    addTrack,
    copyClip,
    deleteClip,
    duplicateClip,
    pasteClip,
    save,
    splitClip,
    toggleLoop,
  } from "$lib/actions.svelte";
  import { api } from "$lib/api";
  import { recorder } from "$lib/recorder.svelte";
  import Arrangement from "$lib/components/Arrangement.svelte";
  import HelpDialog from "$lib/components/HelpDialog.svelte";
  import OpenDialog from "$lib/components/OpenDialog.svelte";
  import Panel, { TABS, type Tab } from "$lib/components/Panel.svelte";
  import Toast from "$lib/components/Toast.svelte";
  import TopBar from "$lib/components/TopBar.svelte";
  import { daw } from "$lib/daw.svelte";
  import { toast } from "$lib/toast.svelte";
  import { transport } from "$lib/transport.svelte";
  import type { Catalogue, Project, Status } from "$lib/types";
  import { isTyping } from "$lib/util";
  import { view } from "$lib/view.svelte";

  let tab = $state<Tab>("clip");
  let expressionInput = $state<HTMLInputElement>();
  let openDialog = $state<OpenDialog>();
  let helpDialog = $state<HelpDialog>();

  // the mix follows the latest render
  $effect(() => transport.setSource(daw.render?.audio?.url ?? null));

  function focusClip() {
    tab = "clip";
    requestAnimationFrame(() => {
      expressionInput?.focus();
      expressionInput?.select();
    });
  }

  function onkeydown(event: KeyboardEvent) {
    if (!daw.ready) return; // ignore shortcuts until the project has loaded
    const mod = event.metaKey || event.ctrlKey;
    const key = event.key.toLowerCase();
    if (mod && key === "s") {
      event.preventDefault();
      void save();
      return;
    }
    if (isTyping(event)) return; // inputs keep their own shortcuts
    if (mod) {
      const commands: Record<string, () => void> = {
        z: event.shiftKey ? daw.redo : daw.undo,
        y: daw.redo,
        d: duplicateClip,
        e: splitClip,
        c: copyClip,
        v: pasteClip,
      };
      const command = commands[key];
      if (command) {
        if (key !== "c" && key !== "v") event.preventDefault();
        command();
      }
      return;
    }
    if (event.code === "Space") {
      event.preventDefault();
      // a focused button would also "click" on key-up and toggle a second time
      if (event.target instanceof HTMLButtonElement) event.target.blur();
      transport.toggle();
    } else if (key === "backspace" || key === "delete") {
      event.preventDefault();
      deleteClip();
    } else if (key === "home" || key === "enter") {
      transport.toStart();
    } else if (key === "l") {
      toggleLoop();
    } else if (key === "r") {
      recorder.toggle();
    } else if (key === "k") {
      transport.metronome.toggle();
    } else if (key === "m" || key === "s") {
      const track = daw.selectedTrack;
      const field = key === "m" ? "mute" : "solo";
      if (track) daw.edit(() => (track[field] = !track[field]));
    } else if (key === "t") {
      addTrack();
    } else if (key === "=" || key === "+") {
      view.zoomAt(1.4);
    } else if (key === "-") {
      view.zoomAt(1 / 1.4);
    } else if (key === "f") {
      view.fit(daw.songLength);
    } else if (key === "?") {
      helpDialog?.show();
    } else if (/^[1-9]$/.test(key) && Number(key) <= TABS.length) {
      tab = TABS[Number(key) - 1][0];
    }
  }

  onMount(() => {
    let frame = 0;
    const loop = () => {
      transport.tick();
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);

    void (async () => {
      try {
        const [catalogue, status] = await Promise.all([
          api.get<Catalogue>("/api/catalogue"),
          api.get<Status>("/api/status"),
        ]);
        daw.catalogue = catalogue;
        daw.status = status;
        const draft = daw.loadDraft();
        if (draft) daw.load(draft.project, { dirty: draft.dirty });
        else daw.load(await api.get<Project>("/api/project/default"));
        view.fit(daw.songLength);
        daw.ready = true;
      } catch (error) {
        toast.show(`Could not start: ${(error as Error).message}`, "err");
      }
    })();
    return () => cancelAnimationFrame(frame);
  });
</script>

<svelte:window
  {onkeydown}
  onbeforeunload={(event) => {
    if (daw.dirty) event.preventDefault();
  }}
/>

<div class="flex h-full flex-col overflow-x-hidden max-[900px]:h-auto">
  <TopBar onopen={() => openDialog?.show()} onhelp={() => helpDialog?.show()} />
  <main class="grid min-h-0 flex-1 grid-rows-[minmax(160px,1fr)_minmax(220px,44vh)] max-[900px]:grid-rows-[420px_auto]">
    <Arrangement onfocusclip={focusClip} />
    <Panel bind:tab bind:expressionInput />
  </main>
</div>

<OpenDialog bind:this={openDialog} />
<HelpDialog bind:this={helpDialog} />
<Toast />
