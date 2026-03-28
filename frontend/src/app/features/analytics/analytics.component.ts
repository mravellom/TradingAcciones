import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-analytics',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './analytics.component.html',
  styleUrl: './analytics.component.scss',
})
export class AnalyticsComponent implements OnInit {
  summary: any = null;
  pnlData: any[] = [];
  drawdownData: any[] = [];
  strategyPerf: any[] = [];
  paperVsLive: any = null;
  mlShadow: any = null;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.api.getAnalyticsSummary().subscribe((s) => (this.summary = s));
    this.api.getCumulativePnl(30).subscribe((d) => (this.pnlData = d));
    this.api.getDrawdown(30).subscribe((d) => (this.drawdownData = d));
    this.api.getPerStrategyPerformance().subscribe((p) => (this.strategyPerf = p));
    this.api.getPaperVsLive().subscribe((d) => (this.paperVsLive = d));
    this.api.getMLShadowPerformance().subscribe((d) => (this.mlShadow = d));
  }

  getPnlClass(value: string | number): string {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    return num > 0 ? 'positive' : num < 0 ? 'negative' : 'neutral';
  }

  formatUsd(value: string): string {
    return parseFloat(value).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  formatPercent(value: number | string): string {
    const num = typeof value === 'string' ? parseFloat(value) : value;
    return (num * 100).toFixed(2) + '%';
  }

  getPnlBarWidth(value: string): number {
    if (!this.pnlData.length) return 0;
    const maxAbs = Math.max(
      ...this.pnlData.map((d) => Math.abs(parseFloat(d.cumulative_pnl)))
    );
    if (maxAbs === 0) return 0;
    return Math.min((Math.abs(parseFloat(value)) / maxAbs) * 100, 100);
  }

  getDrawdownBarWidth(value: string): number {
    if (!this.drawdownData.length) return 0;
    const maxAbs = Math.max(
      ...this.drawdownData.map((d) => Math.abs(parseFloat(d.drawdown_pct || d.drawdown)))
    );
    if (maxAbs === 0) return 0;
    return Math.min((Math.abs(parseFloat(value)) / maxAbs) * 100, 100);
  }
}
