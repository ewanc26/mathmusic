<!-- Upload the current mix to plyr.fm (music on AT Protocol). -->
<script lang="ts">
  import { api } from "$lib/api";
  import { daw } from "$lib/daw.svelte";
  import Field from "./fields/Field.svelte";

  let title = $state("");
  let album = $state("");
  let tags = $state("");
  let description = $state("");
  let busy = $state(false);
  let message = $state("");
  let tone = $state<"" | "ok" | "err">("");

  const status = $derived(daw.status);
  const ready = $derived(Boolean(status.plyrfm && status.plyr_token && daw.render?.audio) && !busy);
  const hint = $derived(
    !status.plyrfm
      ? "The plyrfm package is not installed: uv pip install plyrfm==0.0.1a25"
      : !status.plyr_token
        ? "Set PLYR_TOKEN and restart mathmusic to publish. Create a token at plyr.fm/settings#developer. Your account needs an artist profile."
        : !daw.render?.audio
          ? "Nothing rendered yet."
          : "Uploads the current mix as an MP3 to your plyr.fm account.",
  );

  async function publish() {
    const audio = daw.render?.audio;
    if (!audio) return;
    busy = true;
    tone = "";
    message = "Uploading to plyr.fm… this can take a minute.";
    try {
      const data = await api.post<{ track_id: number }>("/api/publish", {
        render_id: audio.id,
        title: title.trim() || daw.project.name,
        album,
        tags,
        description,
      });
      tone = "ok";
      message = `Published to plyr.fm as track ${data.track_id}.`;
    } catch (error) {
      tone = "err";
      message = (error as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="max-w-[520px]">
  <p class="hint mb-2">{hint}</p>
  <Field label="Title"
    ><input class="input" type="text" maxlength="200" placeholder={daw.project.name} bind:value={title} /></Field
  >
  <Field label="Album"><input class="input" type="text" maxlength="200" bind:value={album} /></Field>
  <Field label="Tags"><input class="input" type="text" placeholder="math, generative" bind:value={tags} /></Field>
  <Field label="Description"
    ><textarea class="input" rows="3" maxlength="2000" bind:value={description}></textarea></Field
  >
  <button class="btn primary" type="button" disabled={!ready} onclick={publish}>Publish to plyr.fm</button>
  {#if message}
    <p
      class="mt-2 text-xs"
      class:text-good={tone === "ok"}
      class:text-bad={tone === "err"}
      class:text-muted={!tone}
      role="status"
    >
      {message}
    </p>
  {/if}
</div>
