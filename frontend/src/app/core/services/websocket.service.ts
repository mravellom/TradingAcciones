import { Injectable, OnDestroy } from '@angular/core';
import { Observable, Subject, timer, EMPTY } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';
import { retry, tap, switchMap, catchError, filter, map } from 'rxjs/operators';
import { WSMessage } from '../../shared/models/trading.models';

import { environment } from '../../../environments/environment';

const WS_URL = environment.wsUrl;
const RECONNECT_INTERVAL = 3000;

@Injectable({ providedIn: 'root' })
export class WebSocketService implements OnDestroy {
  private socket$: WebSocketSubject<any> | null = null;
  private messages$ = new Subject<WSMessage>();
  private isConnected = false;

  connect(
    channels: string[] = [
      'portfolio',
      'positions',
      'signals',
      'orders',
      'risk',
      'system',
    ]
  ): void {
    if (this.socket$) {
      return;
    }

    const channelParam = channels.join(',');
    this.socket$ = webSocket({
      url: `${WS_URL}?channels=${channelParam}`,
      openObserver: {
        next: () => {
          this.isConnected = true;
          console.log('[WS] Connected');
        },
      },
      closeObserver: {
        next: () => {
          this.isConnected = false;
          console.log('[WS] Disconnected, reconnecting...');
          this.socket$ = null;
          // Auto-reconnect
          setTimeout(() => this.connect(channels), RECONNECT_INTERVAL);
        },
      },
    });

    this.socket$.subscribe({
      next: (msg) => this.messages$.next(msg as WSMessage),
      error: (err) => {
        console.error('[WS] Error:', err);
        this.socket$ = null;
        setTimeout(() => this.connect(channels), RECONNECT_INTERVAL);
      },
    });
  }

  disconnect(): void {
    if (this.socket$) {
      this.socket$.complete();
      this.socket$ = null;
    }
    this.isConnected = false;
  }

  /**
   * Get all messages from a specific channel.
   */
  onChannel(channel: string): Observable<WSMessage> {
    return this.messages$.pipe(filter((msg) => msg.channel === channel));
  }

  /**
   * Get messages for a specific event type.
   */
  onEvent(channel: string, event: string): Observable<any> {
    return this.messages$.pipe(
      filter((msg) => msg.channel === channel && msg.event === event),
      map((msg) => msg.data)
    );
  }

  /**
   * Subscribe to additional channels at runtime.
   */
  subscribe(channels: string[]): void {
    if (this.socket$) {
      this.socket$.next(`subscribe:${channels.join(',')}`);
    }
  }

  /**
   * Unsubscribe from channels.
   */
  unsubscribe(channels: string[]): void {
    if (this.socket$) {
      this.socket$.next(`unsubscribe:${channels.join(',')}`);
    }
  }

  get connected(): boolean {
    return this.isConnected;
  }

  ngOnDestroy(): void {
    this.disconnect();
    this.messages$.complete();
  }
}
