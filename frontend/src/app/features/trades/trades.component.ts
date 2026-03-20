import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ApiService } from '../../core/services/api.service';
import { Trade, Order } from '../../shared/models/trading.models';

@Component({
  selector: 'app-trades',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './trades.component.html',
  styleUrl: './trades.component.scss',
})
export class TradesComponent implements OnInit {
  trades: Trade[] = [];
  orders: Order[] = [];
  activeTab: 'trades' | 'orders' = 'trades';
  winRate: number = 0;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadTrades();
    this.loadOrders();
  }

  loadTrades(): void {
    this.api.getTrades(100).subscribe((t) => (this.trades = t));
    this.api.getWinRate().subscribe((r) => (this.winRate = r.win_rate));
  }

  loadOrders(): void {
    this.api.getOrders(100).subscribe((o) => (this.orders = o));
  }

  getPnlClass(value: string): string {
    const num = parseFloat(value);
    return num > 0 ? 'positive' : num < 0 ? 'negative' : 'neutral';
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

  getStatusClass(status: string): string {
    switch (status) {
      case 'FILLED': return 'badge-buy';
      case 'REJECTED':
      case 'CANCELLED': return 'badge-sell';
      case 'PENDING':
      case 'SUBMITTED': return 'badge-open';
      default: return 'badge-closed';
    }
  }
}
