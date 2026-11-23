// [10g] chartDays — the x-axis of DailyRateChart once a recheck has run (D-05)
// Domain's daily rates stop at the last day of data; a run recheck's `after`
// window lies past it. These pure helpers extend the axis with empty days.


// 'YYYY-MM-DD' + n days → 'YYYY-MM-DD'. UTC arithmetic on a plain date, so no
// time zone or DST shift can move it.
export const addDays = (ymd, n) => {
  const d = new Date(`${ymd}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

// The case's most recently run recheck, or null. Only a run recheck has `after`.
export const latestRanRecheck = (rechecks = []) =>
  rechecks
    .filter((r) => r.status !== 'scheduled' && r.after)
    .reduce((latest, r) => (!latest || (r.ran_at ?? '') > (latest.ran_at ?? '') ? r : latest), null);

// Every day the x-axis shows: the daily rates, then (after a recheck) empty days
// up to the end of its after window. → [{ date, rate, claims, eligible_orders } | { date, future: true }]
export const chartDays = (dailyRates, recheck) => {
  const days = [...dailyRates];
  const end = recheck?.after?.end;
  let date = dailyRates.at(-1)?.date;
  while (end && date && date < end) {
    date = addDays(date, 1);
    days.push({ date, future: true });
  }
  return days;
};
