import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-approval-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './approval-modal.component.html',
  styleUrl: './approval-modal.component.scss',
})
export class ApprovalModalComponent {
  @Input() order: any = null;
  @Input() visible = false;
  @Output() approved = new EventEmitter<string>();
  @Output() rejected = new EventEmitter<{ id: string; reason: string }>();
  @Output() closed = new EventEmitter<void>();

  rejectReason = '';
  loading = false;

  approve() {
    if (!this.order) return;
    this.loading = true;
    this.approved.emit(this.order.id);
  }

  reject() {
    if (!this.order) return;
    this.loading = true;
    this.rejected.emit({ id: this.order.id, reason: this.rejectReason || 'Manually rejected' });
  }

  close() {
    this.rejectReason = '';
    this.loading = false;
    this.closed.emit();
  }

  onDone() {
    this.loading = false;
    this.close();
  }
}
