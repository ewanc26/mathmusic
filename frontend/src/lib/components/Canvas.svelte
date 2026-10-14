<!--
  A canvas that redraws whenever its size changes or any reactive state read
  by `draw` changes. Extra props (event handlers, aria-label) pass through.
-->
<script lang="ts">
  import type { HTMLCanvasAttributes } from "svelte/elements";

  interface Props extends HTMLCanvasAttributes {
    draw: (canvas: HTMLCanvasElement) => void;
    element?: HTMLCanvasElement;
  }

  let { draw, element = $bindable(), ...rest }: Props = $props();
  let size = $state(0);

  $effect(() => {
    if (!element) return;
    const observer = new ResizeObserver(() => size++);
    observer.observe(element);
    return () => observer.disconnect();
  });

  $effect(() => {
    void size;
    if (element && element.clientWidth > 0) draw(element);
  });
</script>

<canvas bind:this={element} {...rest}></canvas>
