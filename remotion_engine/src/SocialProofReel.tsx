import React from 'react';
import { AbsoluteFill, Img, Sequence, useCurrentFrame, useVideoConfig, spring, interpolate, Audio, staticFile } from 'remotion';
import { z } from 'zod';
import './index.css'; // Make sure Tailwind is loaded

// Zod Schema matching metadata.json
export const reviewSchema = z.object({
  reviewer_name: z.string(),
  review_text: z.string(),
  rating: z.number(),
  avatar_url: z.string().optional(),
  avatar_local_path: z.string().optional(),
});

export const socialProofSchema = z.object({
  business_id: z.string(),
  business_name: z.string(),
  overall_rating: z.number(),
  address: z.string().optional(),
  place_id: z.string().optional(),
  status: z.string().optional(),
  background_local_path: z.string().optional(),
  reviews: z.array(reviewSchema),
});

export type SocialProofProps = z.infer<typeof socialProofSchema>;

// Component for a Single Review
const ReviewSlide: React.FC<{
  review: z.infer<typeof reviewSchema>;
  business_name: string;
  overall_rating: number;
  business_id: string;
  index: number;
}> = ({ review, business_name, overall_rating, business_id, index }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entrance animation for the card
  const entranceProgress = spring({
    frame,
    fps,
    config: { damping: 12 },
  });

  const translateY = interpolate(entranceProgress, [0, 1], [100, 0]);
  const opacity = interpolate(entranceProgress, [0, 1], [0, 1]);

  // Read the local file that was copied to public/leads/{id}/ by the orchestrator
  // By using staticFile, Remotion serves it via its local HTTP server, avoiding the file:// security block
  const avatarSrc = staticFile(`leads/${business_id}/avatar_${index}.jpg`);

  // Generate 5 stars
  const stars = Array.from({ length: 5 }).map((_, i) => (
    <svg
      key={i}
      className={`w-14 h-14 ${i < review.rating ? 'text-[#fbbc04]' : 'text-gray-400'}`}
      fill="currentColor"
      viewBox="0 0 24 24"
    >
      <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
    </svg>
  ));

  return (
    <AbsoluteFill className="items-center justify-center font-sans text-white" style={{ opacity, transform: `translateY(${translateY}px)` }}>
      
      {/* Top Label */}
      <div className="absolute top-24 text-4xl text-gray-300 tracking-wider uppercase font-semibold">
        Reseñas de Google
      </div>

      {/* Main Review Content Container */}
      <div className="flex flex-col items-center justify-center w-[900px] mt-10">
        
        {/* Giant Avatar */}
        {avatarSrc ? (
          <Img
            src={avatarSrc}
            className="w-[432px] h-[432px] rounded-full object-cover border-8 border-white shadow-2xl mb-12"
          />
        ) : (
          <div className="w-[432px] h-[432px] rounded-full bg-blue-600 border-8 border-white shadow-2xl mb-12 flex items-center justify-center text-9xl font-bold">
            {review.reviewer_name.charAt(0).toUpperCase()}
          </div>
        )}

        {/* Reviewer Name */}
        <h2 className="text-6xl font-bold mb-4 text-center drop-shadow-md">
          {review.reviewer_name}
        </h2>

        {/* Stars */}
        <div className="flex space-x-2 mb-10 drop-shadow-md">
          {stars}
        </div>

        <div className="w-full h-1 bg-white/15 mb-10 rounded-full"></div>

        {/* Review Text */}
        <p className="text-5xl text-center leading-tight font-medium drop-shadow-md whitespace-pre-wrap px-4 line-clamp-6">
          {review.review_text}
        </p>
      </div>

      {/* Footer: Business Name & Overall Rating */}
      <div className="absolute bottom-32 flex flex-col items-center w-[900px]">
        <div className="w-full h-1 bg-white/15 mb-10 rounded-full"></div>
        <h3 className="text-5xl font-bold text-center drop-shadow-md mb-4">
          {business_name}
        </h3>
        <div className="flex items-center space-x-3 text-4xl font-bold text-[#fbbc04]">
          <span>{overall_rating}</span>
          <svg className="w-10 h-10" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
          </svg>
        </div>
      </div>

      {/* Watermark */}
      <div className="absolute bottom-10 text-3xl text-white/40 tracking-widest">
        leandrovenegas.cl
      </div>

    </AbsoluteFill>
  );
};

export const SocialProofReel: React.FC<SocialProofProps> = (props) => {
  const { fps } = useVideoConfig();
  
  // Each review gets 6 seconds
  const slideDurationFrames = 6 * fps;
  
  // Same for background, use staticFile and the public copied image
  const bgImage = staticFile(`leads/${props.business_id}/background.jpg`);

  return (
    <AbsoluteFill className="bg-[#0F0F1A]">
      {/* Audio de fondo */}
      <Audio src={staticFile("audio.mp3")} volume={0.5} />

      {/* Background with blur and darkening */}
      <AbsoluteFill>
        {bgImage ? (
          <div 
            className="w-full h-full bg-cover bg-center opacity-30 blur-[15px] scale-110"
            style={{ backgroundImage: `url('${bgImage}')` }}
          />
        ) : (
          <div className="w-full h-full bg-gradient-to-br from-blue-900/20 to-[#0F0F1A]" />
        )}
      </AbsoluteFill>

      {/* Reviews Sequence */}
      {props.reviews.slice(0, 3).map((review, index) => (
        <Sequence
          key={index}
          from={index * slideDurationFrames}
          durationInFrames={slideDurationFrames}
        >
          <ReviewSlide 
            review={review} 
            business_name={props.business_name} 
            overall_rating={props.overall_rating} 
            business_id={props.business_id}
            index={index}
          />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
