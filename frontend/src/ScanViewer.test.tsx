import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ScanViewer from './ScanViewer';

function setup() {
  const onLoad = vi.fn();
  const onError = vi.fn();
  const view = render(
    <ScanViewer
      scanUrl="/api/scans/card1"
      cardId="card1"
      alt="Original coding card: scan.pdf, page 21"
      onLoad={onLoad}
      onError={onError}
    />,
  );
  const image = screen.getByRole('img', { name: /Original coding card/ });
  return { ...view, image, onLoad, onError };
}

describe('ScanViewer', () => {
  it('keeps controls disabled until actual evidence loads, and disables them again on error', async () => {
    const { image, onLoad, onError } = setup();
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled();
    fireEvent.load(image);
    expect(onLoad).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Magnifier (M)' }));
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    fireEvent.error(image);
    expect(onError).toHaveBeenCalledOnce();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled();
    expect(screen.queryByText('2.5×')).not.toBeInTheDocument();
  });

  it('fits by intrinsic aspect ratio, bounds zoom and supports focused keyboard controls', async () => {
    const { image } = setup();
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    Object.defineProperties(image, {
      naturalWidth: { value: 1200 },
      naturalHeight: { value: 600 },
    });
    Object.defineProperties(viewport, {
      clientWidth: { value: 800 },
      clientHeight: { value: 300 },
    });
    fireEvent.load(image);
    expect(image.parentElement).toHaveStyle({ width: '600px' });
    viewport.focus();
    fireEvent.keyDown(viewport, { key: '+' });
    expect(screen.getByText('125%')).toBeInTheDocument();
    expect(image.parentElement).toHaveStyle({ width: '750px' });
    for (let n = 0; n < 20; n++) fireEvent.keyDown(viewport, { key: '+' });
    expect(screen.getByText('400%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeDisabled();
    for (let n = 0; n < 20; n++) fireEvent.keyDown(viewport, { key: '-' });
    expect(screen.getByText('50%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Zoom out' })).toBeDisabled();
    fireEvent.keyDown(viewport, { key: '+', ctrlKey: true });
    expect(screen.getByText('50%')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fit whole card' }));
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(viewport).toHaveAccessibleDescription(/Use \+ and − to zoom/);
  });

  it('magnifies the actual scan under the pointer and hides the lens on leaving or scrolling', () => {
    // jsdom has no PointerEvent constructor; MouseEvent preserves the coordinates we need.
    vi.stubGlobal('PointerEvent', MouseEvent);
    const { image, container } = setup();
    vi.spyOn(image, 'getBoundingClientRect').mockReturnValue({
      left: 10,
      top: 20,
      width: 800,
      height: 400,
      right: 810,
      bottom: 420,
      x: 10,
      y: 20,
      toJSON: () => ({}),
    });
    fireEvent.load(image);
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    fireEvent.keyDown(viewport, { key: 'm' });
    fireEvent.pointerMove(image, { clientX: 210, clientY: 120 });
    const lens = container.querySelector('.scan-lens')!;
    expect(lens).toHaveStyle({ left: '80px', top: '-20px' });
    expect(lens.querySelector('img')).toHaveAttribute('src', '/api/scans/card1');
    expect(lens.querySelector('img')).toHaveStyle({
      width: '2000px',
      height: '1000px',
      left: '-383px',
      top: '-133px',
    });
    fireEvent.pointerLeave(image);
    expect(container.querySelector('.scan-lens')).toBeNull();
    fireEvent.pointerMove(image, { clientX: 210, clientY: 120 });
    fireEvent.scroll(viewport);
    expect(container.querySelector('.scan-lens')).toBeNull();
    fireEvent.pointerMove(image, { clientX: 210, clientY: 120 });
    fireEvent.keyDown(viewport, { key: 'm' });
    expect(container.querySelector('.scan-lens')).toBeNull();
  });

  it('does not apply scan keyboard shortcuts outside the focused scan area', () => {
    const { image } = setup();
    fireEvent.load(image);
    fireEvent.keyDown(document.body, { key: '+' });
    fireEvent.keyDown(document.body, { key: 'm' });
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('respects the single-letter shortcut setting while keeping zoom and mouse controls available', async () => {
    render(
      <ScanViewer
        scanUrl="/api/scans/card1"
        cardId="card1"
        alt="Original scan"
        onLoad={() => {}}
        onError={() => {}}
        shortcutsEnabled={false}
      />,
    );
    fireEvent.load(screen.getByRole('img', { name: 'Original scan' }));
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    fireEvent.keyDown(viewport, { key: 'm' });
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    fireEvent.keyDown(viewport, { key: '+' });
    expect(screen.getByText('125%')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Magnifier (M)' }));
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  it('changes lens size with + and − while retaining scan zoom and 2.5× magnification', async () => {
    const { image } = setup();
    fireEvent.load(image);
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    fireEvent.keyDown(viewport, { key: '+' });
    fireEvent.keyDown(viewport, { key: 'm' });
    expect(screen.getByText('240px')).toBeInTheDocument();
    fireEvent.keyDown(viewport, { key: '+' });
    expect(screen.getByText('280px')).toBeInTheDocument();
    for (let n = 0; n < 10; n++) fireEvent.keyDown(viewport, { key: '+' });
    expect(screen.getByRole('button', { name: 'Larger magnifier lens' })).toBeDisabled();
    expect(screen.getByText('360px')).toBeInTheDocument();
    for (let n = 0; n < 10; n++) fireEvent.keyDown(viewport, { key: '-' });
    expect(screen.getByRole('button', { name: 'Smaller magnifier lens' })).toBeDisabled();
    expect(screen.getByText('160px')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Magnifier (M)' }));
    expect(screen.getByText('125%')).toBeInTheDocument();
  });

  it('keeps view settings on the same card but waits for each new evidence image', () => {
    const props = {
      scanUrl: '/api/scans/card1',
      cardId: 'card1',
      alt: 'Original scan',
      onLoad: vi.fn(),
      onError: vi.fn(),
    };
    const { rerender } = render(
      <ScanViewer key="card1" {...props} evidenceKey="field1" />,
    );
    const oldImage = screen.getByRole('img', { name: 'Original scan' });
    fireEvent.load(oldImage);
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    fireEvent.keyDown(viewport, { key: '+' });
    fireEvent.keyDown(viewport, { key: 'm' });
    fireEvent.keyDown(viewport, { key: '+' });
    rerender(<ScanViewer key="card1" {...props} evidenceKey="field2" />);
    expect(screen.getByRole('img', { name: 'Original scan' })).not.toBe(oldImage);
    expect(screen.getByRole('button', { name: 'Larger magnifier lens' })).toBeDisabled();
    expect(screen.getByText('280px')).toBeInTheDocument();
    fireEvent.load(oldImage);
    expect(screen.getByRole('button', { name: 'Larger magnifier lens' })).toBeDisabled();
    expect(props.onLoad).toHaveBeenCalledTimes(1);
    fireEvent.load(screen.getByRole('img', { name: 'Original scan' }));
    fireEvent.keyDown(viewport, { key: 'm' });
    expect(screen.getByText('125%')).toBeInTheDocument();
    rerender(<ScanViewer key="card2" {...props} cardId="card2" evidenceKey="field3" />);
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Magnifier (M)' })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
  });

  it('pans by dragging the scan, stops on release, and leaves normal image dragging disabled', () => {
    vi.stubGlobal('PointerEvent', MouseEvent);
    const { image } = setup();
    fireEvent.load(image);
    const viewport = screen.getByRole('region', { name: /Scan image/ });
    expect(image).toHaveAttribute('draggable', 'false');
    viewport.scrollLeft = 100;
    viewport.scrollTop = 80;
    fireEvent.pointerDown(image, { button: 0, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(image, { clientX: 150, clientY: 120 });
    expect(viewport.scrollLeft).toBe(150);
    expect(viewport.scrollTop).toBe(160);
    fireEvent.pointerUp(viewport);
    fireEvent.pointerMove(image, { clientX: 50, clientY: 20 });
    expect(viewport.scrollLeft).toBe(150);
    expect(viewport.scrollTop).toBe(160);
    expect(viewport).toHaveFocus();
  });
});
