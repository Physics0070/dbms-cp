/** Minimal line diff (longest common subsequence). Returns the 0-based indices of lines
 *  that were removed from `a` and added in `b`. No dependency — SQL here is a few dozen lines. */
export function diffLines(a: string, b: string): { removed: Set<number>; added: Set<number> } {
  const x = a.split("\n").map((l) => l.trim());
  const y = b.split("\n").map((l) => l.trim());
  const n = x.length, m = y.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const removed = new Set<number>();
  const added = new Set<number>();
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) removed.add(i++);
    else added.add(j++);
  }
  while (i < n) removed.add(i++);
  while (j < m) added.add(j++);
  return { removed, added };
}
