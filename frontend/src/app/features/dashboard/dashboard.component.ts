import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, DecimalPipe } from '@angular/common';
import { Subject, interval } from 'rxjs';
import { takeUntil, switchMap, startWith } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import { NotificationService } from '../../core/services/notification.service';
import { ApprovalModalComponent } from '../../shared/components/approval-modal/approval-modal.component';
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
  imports: [CommonModule, ApprovalModalComponent],
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
  selectedApproval: any = null;
  showApprovalModal = false;

  private destroy$ = new Subject<void>();

  constructor(
    private api: ApiService,
    public ws: WebSocketService,
    private notification: NotificationService,
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
    this.api.getPortfolio().subscribe((p) => (this.portfolio = p));
    this.api.getOpenPositions().subscribe((p) => (this.openPositions = p));
    this.api.getTrades(10).subscribe((t) => (this.recentTrades = t));
    this.api.getSignals(10).subscribe((s) => (this.recentSignals = s));
    this.api.getHealth().subscribe((h) => (this.health = h));
    this.api.getWinRate().subscribe((r) => (this.winRate = r.win_rate));
    this.api.getAnalyticsSummary().subscribe((s) => (this.summary = s));
    this.api.getPerStrategyPerformance().subscribe((p) => (this.strategyPerf = p));
    this.api.getCumulativePnl(30).subscribe((d) => (this.pnlData = d));
    this.api.getPendingApprovals().subscribe((a) => (this.pendingApprovals = a));
  }

  openApproval(order: any): void {
    this.selectedApproval = order;
    this.showApprovalModal = true;
  }

  onApproved(orderId: string): void {
    this.api.approveOrder(orderId).subscribe({
      next: () => {
        this.notification.success('Order approved');
        this.showApprovalModal = false;
        this.selectedApproval = null;
        this.loadData();
      },
      error: () => {
        this.showApprovalModal = false;
      },
    });
  }

  onRejected(event: { id: string; reason: string }): void {
    this.api.rejectOrder(event.id, event.reason).subscribe({
      next: () => {
        this.notification.warning('Order rejected');
        this.showApprovalModal = false;
        this.selectedApproval = null;
        this.loadData();
      },
      error: () => {
        this.showApprovalModal = false;
      },
    });
  }

  onModalClosed(): void {
    this.showApprovalModal = false;
    this.selectedApproval = null;
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
