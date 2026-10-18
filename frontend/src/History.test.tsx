import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import History from './History';
import type { Decision, Item } from './api';
it('keeps an imported correction original honest even after its first audited acceptance', () => {
  const before = {
    value: '009',
    status: 'ok' as const,
    confidence: null,
    origin: 'corrected',
    original_value: '04',
  };
  render(
    <History
      onClose={() => {}}
      item={
        {
          label: 'Weekly Rent',
          field: {
            ...before,
            review: {
              state: 'accepted',
              history: [
                {
                  id: 'audit',
                  action: 'accept',
                  reviewer: 'Reviewer',
                  timestamp: '2026-10-14T07:00:00Z',
                  before,
                  after: before,
                },
              ],
            },
          },
        } as Item
      }
    />,
  );
  const history = screen.getByRole('region', {
    name: 'History of Weekly Rent',
  });
  expect(history).toHaveTextContent(
    'Machine read: 04 · Original status not recorded · Not scored',
  );
  expect(history).toHaveTextContent('Accepted: 009 → 009');
});

it('distinguishes blank and illegible decisions and marks their undone targets', () => {
  const before = { value: '04', status: 'ok' as const, confidence: 0.91 };
  const blank = { value: null, status: 'no_data' as const, confidence: 0.91 };
  const unreadable = { ...blank, status: 'illegible' as const };
  const common = { reviewer: 'Reviewer', timestamp: '2026-10-14T07:00:00Z' };
  const history: Decision[] = [
    { ...common, id: 'blank', action: 'no_data', before, after: blank },
    {
      ...common,
      id: 'undo-blank',
      action: 'undo',
      undo_target: 'blank',
      before: blank,
      after: before,
    },
    { ...common, id: 'illegible', action: 'illegible', before, after: unreadable },
  ];
  render(
    <History
      onClose={() => {}}
      item={
        {
          label: 'Weekly Rent',
          field: { ...unreadable, review: { state: 'corrected', history } },
        } as Item
      }
    />,
  );
  const entries = screen.getAllByRole('listitem');
  expect(entries[0]).toHaveTextContent('Marked blank: 04 → Blank');
  expect(entries[0]).toHaveTextContent('This decision was undone.');
  expect(entries[1]).toHaveTextContent('Undone: Blank → 04');
  expect(entries[2]).toHaveTextContent("Marked illegible: 04 → Can't read it");
  expect(entries[2]).not.toHaveTextContent('This decision was undone.');
});
