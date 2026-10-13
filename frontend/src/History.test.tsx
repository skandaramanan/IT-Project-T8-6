import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import History from './History';
import type { Item } from './api';
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
