import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ImageUploader } from "./ImageUploader";

function makeFile(name: string, type: string, content = "x"): File {
  return new File([content], name, { type });
}

describe("ImageUploader", () => {
  it("calls onFileSelected when a valid image is chosen via the file input (click to upload)", async () => {
    const onFileSelected = vi.fn();
    render(<ImageUploader onFileSelected={onFileSelected} />);

    const file = makeFile("photo.png", "image/png");
    const input = screen.getByLabelText(/選擇圖片/) as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(onFileSelected).toHaveBeenCalledTimes(1);
    expect(onFileSelected.mock.calls[0][0]).toBe(file);
  });

  it("rejects a non-image file with a Traditional Chinese message and does not call onFileSelected", () => {
    // Dropped via drag-and-drop rather than userEvent.upload(): the <input
    // accept="image/*"> attribute makes real browsers (and
    // @testing-library/user-event, which honors it) refuse to even apply a
    // mismatched file to the input — but that's a browser file-picker
    // affordance, not the app's own validation, so this test exercises the
    // drop path where no such filtering happens, to prove the APP's
    // validateSelectedFile() rejection (not just the OS file picker) works.
    const onFileSelected = vi.fn();
    render(<ImageUploader onFileSelected={onFileSelected} />);

    const file = makeFile("notes.txt", "text/plain");
    const dropzone = screen.getByRole("button");
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(onFileSelected).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("請選擇圖片檔案");
  });

  it("supports drag-and-drop", () => {
    const onFileSelected = vi.fn();
    render(<ImageUploader onFileSelected={onFileSelected} />);

    const file = makeFile("photo.png", "image/png");
    const dropzone = screen.getByRole("button");
    fireEvent.drop(dropzone, { dataTransfer: { files: [file] } });

    expect(onFileSelected).toHaveBeenCalledTimes(1);
  });

  it("is disabled and does not open the file picker when disabled", () => {
    const onFileSelected = vi.fn();
    render(<ImageUploader onFileSelected={onFileSelected} disabled />);
    const input = screen.getByLabelText(/選擇圖片/) as HTMLInputElement;
    expect(input).toBeDisabled();
  });
});
