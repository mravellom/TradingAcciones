import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Subject, interval } from 'rxjs';
import { takeUntil, startWith } from 'rxjs/operators';
import { ApiService } from '../../core/services/api.service';
import { WebSocketService } from '../../core/services/websocket.service';
import { RiskStatus, HealthStatus } from '../../shared/models/trading.models';

@Component({
  selector: 'app-risk-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './risk-panel.component.html',
  styleUrl: './risk-panel.component.scss',
})
export class RiskPanelComponent implements OnInit, OnDestroy {
  riskStatus: RiskStatus | null = null;
  health: HealthStatus | null = null;
  haltReason: string = '';

  private destroy$ = new Subject<void>();

  constructor(
    private api: ApiService,
    private ws: WebSocketService
  ) {}

  ngOnInit(): void {
    interval(5000)
      .pipe(startWith(0), takeUntil(this.destroy$))
      .subscribe(() => this.loadData());

    this.ws
      .onEvent('risk', 'risk_alert')
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this.loadData());

    this.ws
      .onEvent('system', 'system_status')
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this.loadData());
  }

  loadData(): void {
    this.api.getRiskStatus().subscribe((r) => (this.riskStatus = r));
    this.api.getHealth().subscribe((h) => (this.health = h));
  }

  haltSystem(): void {
    const reason = this.haltReason || 'Manual halt from UI';
    this.api.haltSystem(reason).subscribe(() => {
      this.haltReason = '';
      this.loadData();
    });
  }

  resumeSystem(): void {
    this.api.resumeSystem().subscribe(() => this.loadData());
  }

  formatPercent(value: string): string {
    return (parseFloat(value) * 100).toFixed(2) + '%';
  }

  getCheckClass(status: string): string {
    return status === 'healthy' ? 'positive' : status === 'unhealthy' ? 'negative' : 'neutral';
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
