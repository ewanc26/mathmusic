// A single transient message at the bottom of the screen.

class Toast {
  text = $state("");
  kind = $state<"" | "ok" | "err">("");
  visible = $state(false);
  private timer: ReturnType<typeof setTimeout> | undefined;

  show(text: string, kind: "" | "ok" | "err" = ""): void {
    this.text = text;
    this.kind = kind;
    this.visible = true;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => (this.visible = false), 3500);
  }
}

export const toast = new Toast();
