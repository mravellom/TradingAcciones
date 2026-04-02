import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../core/services/api.service';
import { Trade, Order } from '../../shared/models/trading.models';

@Component({
  selector: 'app-trades',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './trades.component.html',
  styleUrl: './trades.component.scss',
})
export class TradesComponent implements OnInit {
  trades: Trade[] = [];
  orders: Order[] = [];
  activeTab: 'trades' | 'orders' = 'trades';
  winRate: number = 0;
  assetFilter: string = '';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.loadData();
  }

  onFilterChange(): void {
    this.loadData();
  }

  loadData(): void {
    const ac = this.assetFilter || undefined;
    this.api.getTrades(100, ac).subscribe((t) => (this.trades = t));
    this.api.getOrders(100, ac).subscribe((o) => (this.orders = o));
    this.api.getWinRate().subscribe((r) => (this.winRate = r.win_rate));
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
