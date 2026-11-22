// [10m] ErrorBoundary — a render error in one page shows a message, not a blank screen (D-06)
// Wraps the <Outlet> in Layout, so the side bar stays usable and the analyst can
// move to another page. Moving to another page (resetKey changes) clears the error.
// Only render errors are caught; failed API calls already show their own error + Retry.


// ═══════════════════════════════════════════════════════════════════
// 1. Imports
// ═══════════════════════════════════════════════════════════════════
import { Component } from 'react';


// ═══════════════════════════════════════════════════════════════════
// 2. ErrorBoundary component
// ═══════════════════════════════════════════════════════════════════
// React only supports error boundaries as class components.
class ErrorBoundary extends Component {
  state = { error: null, resetKey: this.props.resetKey };

  static getDerivedStateFromError(error) {
    return { error };
  }

  // Navigated away → clear the error before rendering the new page
  static getDerivedStateFromProps(props, state) {
    if (props.resetKey !== state.resetKey) return { error: null, resetKey: props.resetKey };
    return null;
  }

  componentDidCatch(error, info) {
    console.error('Page crashed:', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section>
        <h1>Something went wrong</h1>
        <div className='error' role='alert'>
          <p>This page hit an unexpected error. Reload it, or pick another page from the menu.</p>
          <button type='button' onClick={() => window.location.reload()}>Reload</button>
        </div>
      </section>
    );
  }
}


// ═══════════════════════════════════════════════════════════════════
// 3. Export
// ═══════════════════════════════════════════════════════════════════
export default ErrorBoundary;
