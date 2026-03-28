import { Component, OnInit } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { CommonModule } from '@angular/common';
import { WebSocketService } from './core/services/websocket.service';
import { TutorialModalComponent } from './features/tutorial/tutorial-modal.component';
import { ToastComponent } from './shared/components/toast/toast.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive, TutorialModalComponent, ToastComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  showTutorial = false;

  constructor(private ws: WebSocketService) {}

  ngOnInit(): void {
    this.ws.connect();
  }
}
