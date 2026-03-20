import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap, startWith } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import {
  Portfolio,
  Position,
  Trade,
  Signal,
  HealthStatus,
} from '../../shared/models/trading.models';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './dashboard.component.html',
  styleUrl: './dashboard.component.scss',
})
export class DashboardComponent implements OnInit, OnDestroy {
  portfolio: Portfolio | null = null;
  openPositions: Position[] = [];
  recentTrades: Trade[] = [];
  recentSignals: Signal[] = [];
  health: HealthStatus | null = null;
  winRate: number = 0;
  summary: any = null;
  strategyPerf: any[] = [];
  pnlData: any[] = [];
  pendingApprovals: any[] = [];

  private destroy$ = new Subject<void>();

  constructor(
    private api: ApiService,
    public ws: WebSocketService
  ) {}

  ngOnInit(): void {
    // Poll data every 5 seconds
    interval(5000)
      .pipe(startWith(0), takeUntil(this.destroy$))
      .subscribe(() => this.loadData());

    // Listen for real-time updates
    this.ws
      .onEvent('portfolio', 'portfolio_updated')
      .pipe(takeUntil(this.destroy$))
      .subscribe((data) => {
        if (this.portfolio) {
          Object.assign(this.portfolio, data);
        }
      });

    this.ws
      .onEvent('positions', 'position_updated')
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => {
        this.api.getOpenPositions().subscribe((p) => (this.openPositions = p));
      });
  }

  loadData(): void {
    this.api.getPortfolio().subscribe({
      next: (p) => (this.portfolio = p),
      error: () => {},
    });
    this.api.getOpenPositions().subscribe({
      next: (p) => (this.openPositions = p),
      error: () => {},
    });
    this.api.getTrades(10).subscribe({
      next: (t) => (this.recentTrades = t),
      error: () => {},
    });
    this.api.getSignals(10).subscribe({
      next: (s) => (this.recentSignals = s),
      error: () => {},
    });
    this.api.getHealth().subscribe({
      next: (h) => (this.health = h),
      error: () => {},
    });
    this.api.getWinRate().subscribe({
      next: (r) => (this.winRate = r.win_rate),
      error: () => {},
    });
    this.api.getAnalyticsSummary().subscribe({
      next: (s) => (this.summary = s),
      error: () => {},
    });
    this.api.getPerStrategyPerformance().subscribe({
      next: (p) => (this.strategyPerf = p),
      error: () => {},
    });
    this.api.getCumulativePnl(30).subscribe({
      next: (d) => (this.pnlData = d),
      error: () => {},
    });
    this.api.getPendingApprovals().subscribe({
      next: (a) => (this.pendingApprovals = a),
      error: () => {},
    });
  }

  approveOrder(orderId: string): void {
    this.api.approveOrder(orderId).subscribe(() => this.loadData());
  }

  rejectOrder(orderId: string): void {
    this.api.rejectOrder(orderId).subscribe(() => this.loadData());
  }

  getPnlClass(value: string): string {
    const num = parseFloat(value);
    if (num > 0) return 'positive';
    if (num < 0) return 'negative';
    return 'neutral';
  }

  formatUsd(value: string): string {
    return parseFloat(value).toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  formatPercent(value: string): string {
    return (parseFloat(value) * 100).toFixed(2) + '%';
  }

  getPnlBarWidth(value: string): number {
    if (!this.pnlData.length) return 0;
    const maxAbs = Math.max(
      ...this.pnlData.map((d) => Math.abs(parseFloat(d.cumulative_pnl)))
    );
    if (maxAbs === 0) return 0;
    return Math.min((Math.abs(parseFloat(value)) / maxAbs) * 100, 100);
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
