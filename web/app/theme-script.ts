/**
 * Applied before React hydrates, so the interface never paints in the wrong
 * theme and then corrects itself. A flash of the light theme on a dark ground
 * is the first thing a user sees, every single launch.
 *
 * Kept as a string rather than a module because it has to run inline in the
 * document head, before any bundle has loaded.
 */
export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("askwell-theme");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t)}}catch(e){}})()`;
