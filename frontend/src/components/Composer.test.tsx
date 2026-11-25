import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  it("sends on Enter, adds a line on Shift+Enter, and ignores blank messages", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} label="Message Pat" />);
    const box = screen.getByLabelText("Message Pat");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "Hello" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Hello");
    expect(box).toHaveValue("");
  });
});
