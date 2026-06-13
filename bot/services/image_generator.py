import os
import json
import asyncio
from loguru import logger
from playwright.async_api import async_playwright

class ImageGenerator:
    """
    Handles rendering the React HTML templates to PNG images using Playwright.
    """
    
    def __init__(self):
        # We assume the HTML is in the image_generator folder at the root
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.html_path = f"file:///{os.path.join(base_dir, 'image_generator', 'index.html').replace(chr(92), '/')}"
        
        # Ensure output directory exists
        self.output_dir = os.path.join(base_dir, 'output_images')
        os.makedirs(self.output_dir, exist_ok=True)

    async def generate_image(self, view_name: str, match_data: dict, output_filename: str) -> str:
        """
        Generates a PNG screenshot of the specified view.
        
        :param view_name: 'preview-before', 'slip-before', 'preview-after', 'slip-won', 'slip-lost'
        :param match_data: The dictionary containing the temporal UI bindings.
        :param output_filename: Name of the output file (e.g., 'match_101_preview.png')
        :return: Absolute path to the generated image.
        """
        logger.info(f"Generating image for view: {view_name}...")
        
        output_path = os.path.join(self.output_dir, output_filename)
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # We use a mobile viewport roughly matching the CSS frame to ensure perfect rendering
                context = await browser.new_context(viewport={'width': 450, 'height': 900})
                page = await context.new_page()
                
                # Navigate to the local HTML file
                await page.goto(self.html_path)
                
                # Inject the dynamic temporal bindings into the page
                await page.evaluate(f"window.BOT_VIEW = '{view_name}';")
                await page.evaluate(f"window.BOT_DATA = {json.dumps(match_data)};")
                
                # We need to trigger a re-render in React since we injected data after load.
                # A simple way is to re-execute the React render logic, but since Babel compiles it,
                # we can just inject a small script to force the root to re-render.
                # Given our index.html structure, we can just re-mount:
                await page.evaluate("""
                    const rootElement = document.getElementById('root');
                    const root = ReactDOM.createRoot(rootElement);
                    root.render(React.createElement(App));
                """)
                
                # Wait for any network images/fonts to finish
                await page.wait_for_load_state('networkidle')
                await asyncio.sleep(1)  # Extra buffer for animations
                
                # Find the bounding box of the actual iPhone frame to screenshot just that element
                locator = page.locator(".iphone-frame, .card-container").first
                
                if await locator.count() > 0:
                    await locator.screenshot(path=output_path)
                    logger.success(f"Image saved successfully to {output_path}")
                else:
                    logger.error("Could not find the UI element to screenshot. Falling back to full page.")
                    await page.screenshot(path=output_path)
                
                await browser.close()
                return output_path
                
        except Exception as e:
            logger.error(f"Failed to generate image: {e}")
            raise
